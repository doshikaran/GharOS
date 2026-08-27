"""Tests for `app.adapters.vendor_relations` (A33) — deterministic
reliability/latency computation, the T3 reliability-updater's idempotent
write path (real Firestore emulator), and the T2 switch-proposal composer
(fake Gemini, mirroring `test_escalation_agent.py`'s established style).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from contracts.graph_types import AgentId, Derivation, NodeId, Provenance, SourceRef, Vendor
from google.genai import errors as genai_errors

from app.adapters.vendor_relations import (
    VendorRelationsAgent,
    VendorReliabilityUpdater,
    VendorRequestObservation,
    compute_reliability_score,
    compute_response_latency_hours,
)
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.reasoning.gemini_client import GeminiClient
from app.tools.graph_write_tool import GraphWriteTool
from tests._gemini_fakes import FakeModels, fake_router

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _CountingGraphWriter:
    def __init__(self, real: FirestoreGraphWriter) -> None:
        self._real = real
        self.write_node_calls = 0

    def write_node(self, node: Any) -> NodeId:
        self.write_node_calls += 1
        return self._real.write_node(node)

    def write_edge(self, edge: Any) -> None:
        self._real.write_edge(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        return self._real.supersede_node(old_node_id, new_node)


def _vendor(*, reliability_score: float | None = None, response_latency_hours: float | None = None) -> Vendor:
    return Vendor(
        id=NodeId("vendor-plumber"),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-vendor-1"), region="p1"),
            confidence=0.8,
            deriving_agent=AgentId("A5"),
            created_at=NOW,
        ),
        category="plumbing",
        contacts=("+91-90000-00001",),
        reliability_score=reliability_score,
        response_latency_hours=response_latency_hours,
    )


def _obs(
    *,
    requested_at: datetime = NOW,
    responded_at: datetime | None = None,
    promised_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> VendorRequestObservation:
    return VendorRequestObservation(
        vendor_id=NodeId("vendor-plumber"),
        requested_at=requested_at,
        responded_at=responded_at,
        promised_at=promised_at,
        completed_at=completed_at,
    )


class TestComputeReliabilityScore:
    def test_empty_observations_returns_none(self) -> None:
        assert compute_reliability_score(()) is None

    def test_on_time_completion_scores_full(self) -> None:
        obs = _obs(
            responded_at=NOW + timedelta(hours=2),
            promised_at=NOW + timedelta(days=1),
            completed_at=NOW + timedelta(hours=20),
        )
        assert compute_reliability_score((obs,)) == 1.0

    def test_late_completion_scores_partial(self) -> None:
        obs = _obs(
            responded_at=NOW + timedelta(hours=2),
            promised_at=NOW + timedelta(days=1),
            completed_at=NOW + timedelta(days=4),
        )
        assert compute_reliability_score((obs,)) == 0.6

    def test_responded_but_never_completed_scores_low(self) -> None:
        obs = _obs(responded_at=NOW + timedelta(hours=2))
        assert compute_reliability_score((obs,)) == 0.3

    def test_no_response_at_all_scores_zero(self) -> None:
        obs = _obs()
        assert compute_reliability_score((obs,)) == 0.0

    def test_mixed_observations_average_correctly(self) -> None:
        on_time = _obs(
            responded_at=NOW, promised_at=NOW + timedelta(days=1), completed_at=NOW + timedelta(hours=5)
        )
        no_response = _obs()
        score = compute_reliability_score((on_time, no_response))
        assert score == 0.5


class TestComputeResponseLatencyHours:
    def test_no_observations_returns_none(self) -> None:
        assert compute_response_latency_hours(()) is None

    def test_no_responses_yet_returns_none(self) -> None:
        assert compute_response_latency_hours((_obs(), _obs())) is None

    def test_averages_latency_across_responded_observations_only(self) -> None:
        fast = _obs(responded_at=NOW + timedelta(hours=2))
        slow = _obs(responded_at=NOW + timedelta(hours=10))
        never = _obs()
        latency = compute_response_latency_hours((fast, slow, never))
        assert latency == 6.0


class TestVendorReliabilityUpdater:
    def test_no_observations_writes_nothing(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        updater = VendorReliabilityUpdater(
            graph_write_tool=GraphWriteTool(graph_writer=spy, idempotency_store=idempotency_store)
        )
        result = updater.update(vendor=_vendor(), observations=(), as_of=NOW)
        assert result is None
        assert spy.write_node_calls == 0

    def test_unchanged_score_writes_nothing(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        updater = VendorReliabilityUpdater(
            graph_write_tool=GraphWriteTool(graph_writer=spy, idempotency_store=idempotency_store)
        )
        obs = _obs(
            responded_at=NOW, promised_at=NOW + timedelta(days=1), completed_at=NOW + timedelta(hours=5)
        )
        vendor = _vendor(reliability_score=1.0, response_latency_hours=0.0)
        result = updater.update(vendor=vendor, observations=(obs,), as_of=NOW)
        assert result is None
        assert spy.write_node_calls == 0

    def test_changed_score_writes_an_updated_vendor(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        updater = VendorReliabilityUpdater(
            graph_write_tool=GraphWriteTool(graph_writer=spy, idempotency_store=idempotency_store)
        )
        obs = _obs()  # no response at all -> score 0.0
        vendor = _vendor(reliability_score=0.9, response_latency_hours=1.0)

        result = updater.update(vendor=vendor, observations=(obs,), as_of=NOW)

        assert result is not None
        assert result.reliability_score == 0.0
        assert spy.write_node_calls == 1

    def test_replay_with_same_day_bucket_never_double_writes(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        updater = VendorReliabilityUpdater(
            graph_write_tool=GraphWriteTool(graph_writer=spy, idempotency_store=idempotency_store)
        )
        obs = _obs()
        vendor = _vendor(reliability_score=0.9, response_latency_hours=1.0)

        updater.update(vendor=vendor, observations=(obs,), as_of=NOW)
        # Second call against the SAME stale `vendor` (as a real repeated
        # scan that hasn't re-read the graph yet would do) recomputes the
        # same "changed" comparison and calls invoke_idempotent again with
        # the same (vendor_id, day) key — the underlying writer must still
        # only ever be invoked once.
        updater.update(vendor=vendor, observations=(obs,), as_of=NOW)

        assert spy.write_node_calls == 1


def _agent(text: str = "Consider reviewing this vendor's recent history.") -> VendorRelationsAgent:
    return VendorRelationsAgent(gemini_client=GeminiClient(router=fake_router(FakeModels(texts=[text]))))


class TestVendorRelationsAgentSwitchProposal:
    def test_no_observations_produces_no_draft(self) -> None:
        agent = _agent()
        result = agent.propose_switch_if_warranted(vendor=_vendor(), observations=())
        assert result is None

    def test_acceptable_reliability_produces_no_draft(self) -> None:
        agent = _agent()
        obs = _obs(
            responded_at=NOW, promised_at=NOW + timedelta(days=1), completed_at=NOW + timedelta(hours=5)
        )
        result = agent.propose_switch_if_warranted(vendor=_vendor(), observations=(obs,))
        assert result is None

    def test_poor_reliability_produces_a_composed_draft(self) -> None:
        agent = _agent("Consider switching plumbers — three of the last four requests went unanswered.")
        obs = (_obs(), _obs(), _obs())  # no responses at all -> reliability 0.0
        result = agent.propose_switch_if_warranted(vendor=_vendor(), observations=obs)
        assert result is not None
        assert result.is_template_fallback is False
        assert "switching" in result.draft_text.lower()

    def test_gemini_failure_falls_back_to_template(self) -> None:
        api_error = genai_errors.APIError(503, {"error": {"message": "simulated Gemini outage"}})
        broken_client = GeminiClient(router=fake_router(FakeModels(texts=["unused"], error=api_error)))
        agent = VendorRelationsAgent(gemini_client=broken_client)
        result = agent.propose_switch_if_warranted(vendor=_vendor(), observations=(_obs(),))
        assert result is not None
        assert result.is_template_fallback is True
        assert "plumbing" in result.draft_text

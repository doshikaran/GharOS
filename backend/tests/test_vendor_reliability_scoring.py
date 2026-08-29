"""Tests for `app.reasoning.vendor_reliability_scoring` — the Memory
Consolidation service's vendor-reliability-scoring pass (spec §20,
ADR-021 Decision 5).

`test_worked_example_matches_module_docstring` reproduces the module
docstring's worked example exactly — the CTO hand-verifies this digit by
digit at Gate 14 (per this phase's Definition of Done). The write-path
test (`test_score_and_write_supersedes_the_real_vendor_node`) uses the
real Firestore emulator (`writer` fixture, `tests.conftest`), consistent
with this project's "integration tests against the actual emulator, not
mocks" rule — mirrors `test_vendor_relations.py`'s established style for
exactly this same pair of `Vendor` fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.graph_types import AgentId, Derivation, NodeId, Outcome, Provenance, SourceRef, Vendor

from app.graph.writer import FirestoreGraphWriter
from app.reasoning.vendor_reliability_scoring import (
    VendorAttributionReliabilityScorer,
    compute_vendor_reliability_update,
)

NOW = datetime(2026, 8, 29, 21, 0, tzinfo=UTC)


def _outcome(*, outcome_id: str, tags: tuple[str, ...]) -> Outcome:
    return Outcome(
        id=NodeId(outcome_id),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-call-1"), region="transcript"),
            confidence=0.9,
            deriving_agent=AgentId("A55"),
            created_at=NOW,
        ),
        predicted="vendor confirms visit",
        actual="see attribution_tags",
        variance=None,
        attribution_tags=tags,
    )


def _vendor(
    *,
    vendor_id: str = "vendor-1",
    reliability_score: float | None = None,
    response_latency_hours: float | None = None,
) -> Vendor:
    return Vendor(
        id=NodeId(vendor_id),
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


def test_worked_example_matches_module_docstring() -> None:
    """Four outcomes tagged on_time, on_time, no_show, rescheduled; no
    prior latency; three new latency observations of 8/12/16 hours.

    rate_raw           = (1 + 1 - 1 + 0.5) / 4 = 0.375
    rate_score         = (0.375 + 1) / 2       = 0.6875
    updated_latency    = mean(8, 12, 16)       = 12.0
    latency_score      = 1 - 12/48             = 0.75
    reliability_score  = 0.7*0.6875 + 0.3*0.75 = 0.70625
    confidence         = 4 / 5.0               = 0.8
    """
    vendor = _vendor()
    outcomes = (
        _outcome(outcome_id="o1", tags=("on_time",)),
        _outcome(outcome_id="o2", tags=("on_time",)),
        _outcome(outcome_id="o3", tags=("no_show",)),
        _outcome(outcome_id="o4", tags=("rescheduled",)),
    )

    update = compute_vendor_reliability_update(
        vendor=vendor,
        recent_outcomes=outcomes,
        new_latency_observations_hours=(8.0, 12.0, 16.0),
    )

    assert update is not None
    assert update.rate_score == 0.6875
    assert update.latency_score == 0.75
    assert update.new_response_latency_hours == 12.0
    # 0.7*0.6875 + 0.3*0.75 = 0.70625 exactly in decimal arithmetic; binary
    # floating point represents it as 0.7062499999999999 — pytest.approx
    # accounts for that representation gap, not for any rounding in the
    # formula itself (every intermediate value above is asserted exactly).
    assert update.new_reliability_score == pytest.approx(0.70625)
    assert update.informative_tag_count == 4
    assert update.confidence == 0.8


def test_latency_blends_with_prior_value_when_one_exists() -> None:
    """Prior latency 20.0h, one new observation of 10.0h ->
    0.4*10 + 0.6*20 = 4 + 12 = 16.0 (recency-weighted, not overwritten)."""
    vendor = _vendor(response_latency_hours=20.0)
    outcomes = (_outcome(outcome_id="o1", tags=("on_time",)),)

    update = compute_vendor_reliability_update(
        vendor=vendor, recent_outcomes=outcomes, new_latency_observations_hours=(10.0,)
    )

    assert update is not None
    assert update.new_response_latency_hours == 16.0


def test_no_new_latency_observations_carries_prior_value_forward() -> None:
    vendor = _vendor(response_latency_hours=30.0)
    outcomes = (_outcome(outcome_id="o1", tags=("on_time",)),)

    update = compute_vendor_reliability_update(vendor=vendor, recent_outcomes=outcomes)

    assert update is not None
    assert update.new_response_latency_hours == 30.0


def test_no_latency_data_ever_drops_the_latency_component_entirely() -> None:
    vendor = _vendor(response_latency_hours=None)
    outcomes = (_outcome(outcome_id="o1", tags=("on_time",)), _outcome(outcome_id="o2", tags=("no_show",)))

    update = compute_vendor_reliability_update(vendor=vendor, recent_outcomes=outcomes)

    assert update is not None
    assert update.latency_score is None
    assert update.new_response_latency_hours is None
    # rate_raw = (1 - 1) / 2 = 0.0 -> rate_score = 0.5; no latency component -> score is rate_score alone.
    assert update.rate_score == 0.5
    assert update.new_reliability_score == 0.5


def test_no_informative_tags_produces_no_update() -> None:
    """An outcome carrying only unrelated tags (e.g. a Ledger-domain tag)
    is not part of ADR-016's vocabulary and must not fabricate a neutral
    score."""
    vendor = _vendor()
    outcomes = (_outcome(outcome_id="o1", tags=("price_change",)),)

    update = compute_vendor_reliability_update(vendor=vendor, recent_outcomes=outcomes)

    assert update is None


def test_empty_outcomes_produces_no_update() -> None:
    vendor = _vendor()

    update = compute_vendor_reliability_update(vendor=vendor, recent_outcomes=())

    assert update is None


def test_unresponsive_to_automated_caller_weighted_same_as_no_show() -> None:
    vendor = _vendor()
    unresponsive_outcome = _outcome(outcome_id="o1", tags=("unresponsive_to_automated_caller",))
    unresponsive = compute_vendor_reliability_update(vendor=vendor, recent_outcomes=(unresponsive_outcome,))
    no_show = compute_vendor_reliability_update(
        vendor=vendor, recent_outcomes=(_outcome(outcome_id="o1", tags=("no_show",)),)
    )

    assert unresponsive is not None
    assert no_show is not None
    assert unresponsive.rate_score == no_show.rate_score == 0.0


def test_score_and_write_supersedes_the_real_vendor_node(writer: FirestoreGraphWriter) -> None:
    vendor = _vendor(vendor_id="vendor-live")
    writer.write_node(vendor)

    scorer = VendorAttributionReliabilityScorer(graph_writer=writer)
    outcomes = (_outcome(outcome_id="o1", tags=("on_time",)), _outcome(outcome_id="o2", tags=("on_time",)))

    updated = scorer.score_and_write(vendor=vendor, recent_outcomes=outcomes, as_of=NOW)

    assert updated is not None
    assert updated.reliability_score == 1.0
    assert updated.provenance.derivation is Derivation.AMBIGUOUS
    assert updated.provenance.source_ref is None
    assert str(updated.provenance.deriving_agent) == "memory-consolidation-vendor-scoring"


def test_score_and_write_is_a_noop_when_nothing_changed(writer: FirestoreGraphWriter) -> None:
    vendor = _vendor(vendor_id="vendor-stable", reliability_score=1.0, response_latency_hours=None)
    writer.write_node(vendor)

    scorer = VendorAttributionReliabilityScorer(graph_writer=writer)
    outcomes = (_outcome(outcome_id="o1", tags=("on_time",)),)

    updated = scorer.score_and_write(vendor=vendor, recent_outcomes=outcomes, as_of=NOW)

    assert updated is None


def test_score_and_write_returns_none_with_no_informative_signal(writer: FirestoreGraphWriter) -> None:
    vendor = _vendor(vendor_id="vendor-no-signal")
    writer.write_node(vendor)

    scorer = VendorAttributionReliabilityScorer(graph_writer=writer)

    updated = scorer.score_and_write(vendor=vendor, recent_outcomes=(), as_of=NOW)

    assert updated is None

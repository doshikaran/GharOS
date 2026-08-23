"""Tests for A2 Intake Router (`app.agents.intake.intake_router`).

spec §15.2 A2: classify channel/content type + assess relevance, Flash
only, forbidden from extraction/implication/action. *Failure:* unknown
type -> human triage, never silent discard — this suite's central
assertion is that `record_registry_gap` (spec §5.4.3 rule 4) is actually
called on every unresolved path, not just documented as a should-do.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.ingestion import NormalizedIntake
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _registry() -> DocumentTypeRegistry:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    return registry


def _gap_log() -> RegistryGapLog:
    return RegistryGapLog(InMemoryRegistryGapStore())


def _intake(text: str = "Sample content") -> NormalizedIntake:
    return NormalizedIntake(
        channel="email",
        raw_payload_ref="sha256:deadbeef",
        text_content=text,
        media_type="text/plain",
        received_at=datetime(2026, 8, 20, tzinfo=UTC),
        sender="school@example.org",
        participants=(),
        original_language_hint=None,
    )


def _router_for(response_obj: dict[str, object]) -> IntakeRouter:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return IntakeRouter(gemini_client=client, registry=_registry(), gap_log=_gap_log())


class TestSuccessfulClassification:
    def test_confident_known_type_resolves(self) -> None:
        router = _router_for(
            {
                "type_id": "receipt",
                "type_confidence": 0.9,
                "signals_matched": ["merchant_header", "total_line"],
                "runner_up_type_id": None,
                "runner_up_confidence": 0.0,
                "relevance": "relevant",
                "relevance_reason": "Has a total and merchant.",
            }
        )
        result = router.route(_intake())

        assert result.resolved is True
        assert result.classified_type_id == "receipt"
        assert result.registry_gap is None


class TestRegistryGapPaths:
    def test_null_type_id_records_registry_gap(self) -> None:
        router = _router_for(
            {
                "type_id": None,
                "type_confidence": 0.0,
                "signals_matched": [],
                "runner_up_type_id": None,
                "runner_up_confidence": 0.0,
                "relevance": "relevant",
                "relevance_reason": "Unclear.",
            }
        )
        result = router.route(_intake())

        assert result.resolved is False
        assert result.registry_gap is not None
        assert result.registry_gap.channel == "email"

    def test_low_confidence_known_type_still_records_gap(self) -> None:
        """spec §5.4.3 rule 1: misclassification is more damaging than
        low-confidence extraction — a low-confidence guess routes to
        triage rather than being trusted."""
        router = _router_for(
            {
                "type_id": "receipt",
                "type_confidence": 0.1,
                "signals_matched": [],
                "runner_up_type_id": "quote_estimate",
                "runner_up_confidence": 0.08,
                "relevance": "relevant",
                "relevance_reason": "Ambiguous.",
            }
        )
        result = router.route(_intake())

        assert result.resolved is False
        assert result.registry_gap is not None

    def test_model_naming_unregistered_type_records_gap(self) -> None:
        router = _router_for(
            {
                "type_id": "some_type_not_in_the_registry",
                "type_confidence": 0.95,
                "signals_matched": ["x"],
                "runner_up_type_id": None,
                "runner_up_confidence": 0.0,
                "relevance": "relevant",
                "relevance_reason": "n/a",
            }
        )
        result = router.route(_intake())

        assert result.resolved is False
        assert result.registry_gap is not None

    def test_registry_gap_is_actually_queryable_from_the_log(self) -> None:
        """Not just 'raised' — spec §5.4.3 rule 4's "log it as a registry
        gap... this is how the registry grows" requires it be durably
        retrievable, not merely printed."""
        gap_log = _gap_log()
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "type_id": None,
                        "type_confidence": 0.0,
                        "signals_matched": [],
                        "runner_up_type_id": None,
                        "runner_up_confidence": 0.0,
                        "relevance": "relevant",
                        "relevance_reason": "n/a",
                    }
                )
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        router = IntakeRouter(gemini_client=client, registry=_registry(), gap_log=gap_log)

        router.route(_intake())

        assert len(gap_log.list_gaps()) == 1

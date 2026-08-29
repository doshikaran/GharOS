"""Tests for A22 Intention Capture
(`app.agents.intention_action.intention_capture_agent`).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- Stale obligation detected unprompted — a real, deterministic threshold
  check, no model call.
- Passive intention capture recognises a real intention in passing text.
- Forbidden: acting directly — no tool of any kind, no write import.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta

from contracts.graph_types import NodeId, Obligation, ObligationDerivation, ObligationStatus

from app.agents.intention_action.intention_capture_agent import AGENT_ID, IntentionCaptureAgent
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import make_provenance

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _agent(texts: list[str] | None = None) -> IntentionCaptureAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return IntentionCaptureAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _obligation(
    *,
    status: ObligationStatus = ObligationStatus.DERIVED,
    due_at: datetime | None = None,
    must_start_by: datetime | None = None,
    created_at: datetime = _NOW,
) -> Obligation:
    return Obligation(
        id=NodeId("obligation-ac-service"),
        provenance=dataclasses.replace(make_provenance(), created_at=created_at),
        title="Get the AC serviced",
        obligation_type="household_maintenance",
        due_at=due_at,
        must_start_by=must_start_by,
        effort_estimate_minutes=30,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


class TestStaleObligationDetection:
    def test_never_stale_before_deadline(self) -> None:
        agent = _agent()
        obligation = _obligation(due_at=_NOW + timedelta(days=1))

        assert agent.detect_stale_obligation(obligation, now=_NOW) is None

    def test_stale_just_past_deadline_grace(self) -> None:
        agent = _agent()
        obligation = _obligation(due_at=_NOW - timedelta(days=4))

        detection = agent.detect_stale_obligation(obligation, now=_NOW)

        assert detection is not None
        assert detection.obligation_id == obligation.id
        assert detection.days_stale == 4
        assert detection.threshold_days == 3
        assert "4 day" in detection.reason

    def test_not_yet_stale_within_grace_period(self) -> None:
        agent = _agent()
        obligation = _obligation(due_at=_NOW - timedelta(days=1))

        assert agent.detect_stale_obligation(obligation, now=_NOW) is None

    def test_must_start_by_overdue_is_stale(self) -> None:
        agent = _agent()
        obligation = _obligation(must_start_by=_NOW - timedelta(days=10))

        detection = agent.detect_stale_obligation(obligation, now=_NOW)

        assert detection is not None
        assert "must start by" in detection.reason

    def test_no_deadline_untouched_past_threshold_is_stale(self) -> None:
        """Spec's own worked example: an open-ended intention ("call the
        dentist") untouched for months — here, past the documented
        21-day-no-deadline threshold."""
        agent = _agent()
        obligation = _obligation(created_at=_NOW - timedelta(days=120))

        detection = agent.detect_stale_obligation(obligation, now=_NOW)

        assert detection is not None
        assert detection.days_stale == 120
        assert detection.threshold_days == 21

    def test_no_deadline_recently_touched_is_not_stale(self) -> None:
        agent = _agent()
        obligation = _obligation(created_at=_NOW - timedelta(days=2))

        assert agent.detect_stale_obligation(obligation, now=_NOW) is None

    def test_terminal_status_is_never_stale_even_if_deadline_long_passed(self) -> None:
        agent = _agent()
        obligation = _obligation(status=ObligationStatus.COMPLETED, due_at=_NOW - timedelta(days=400))

        assert agent.detect_stale_obligation(obligation, now=_NOW) is None

    def test_dropped_obligation_is_never_stale(self) -> None:
        agent = _agent()
        obligation = _obligation(status=ObligationStatus.DROPPED, due_at=_NOW - timedelta(days=400))

        assert agent.detect_stale_obligation(obligation, now=_NOW) is None

    def test_staleness_check_makes_no_model_call(self) -> None:
        fake_models = FakeModels(texts=["should never be read"])
        agent = IntentionCaptureAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))
        obligation = _obligation(due_at=_NOW - timedelta(days=10))

        agent.detect_stale_obligation(obligation, now=_NOW)

        assert len(fake_models.calls) == 0


class TestPassiveIntentionCapture:
    def test_recognises_a_real_intention(self) -> None:
        response = json.dumps(
            {
                "intention_found": True,
                "intention_summary": "we should really get the AC serviced",
                "suggested_title": "Get the AC serviced",
                "confidence": 0.85,
                "reasoning": "a clear intention stated in passing",
            }
        )
        agent = _agent(texts=[response])

        detection = agent.detect_passive_intention(
            source_text="ugh so hot today, we should really get the AC serviced before summer",
            speaker_person_id=NodeId("person-priya"),
        )

        assert detection is not None
        assert detection.suggested_title == "Get the AC serviced"
        assert detection.person_id == NodeId("person-priya")
        assert detection.source_text.startswith("ugh so hot")

    def test_no_intention_returns_none(self) -> None:
        response = json.dumps(
            {
                "intention_found": False,
                "intention_summary": "",
                "suggested_title": "",
                "confidence": 0.9,
                "reasoning": "just a question, not an intention",
            }
        )
        agent = _agent(texts=[response])

        detection = agent.detect_passive_intention(source_text="what time is it?", speaker_person_id=None)

        assert detection is None


def _references_write_or_tool_machinery() -> bool:
    import ast
    import inspect

    from app.agents.intention_action import intention_capture_agent

    tree = ast.parse(inspect.getsource(intention_capture_agent))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                "graph_write_tool" in node.module or "registry" in node.module or "arbitration" in node.module
            )
        ):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.9 A22 forbidden list: 'acting directly.'"""

    def test_module_has_no_write_or_tool_import(self) -> None:
        assert not _references_write_or_tool_machinery()


def test_agent_id_is_a22() -> None:
    assert str(AGENT_ID) == "A22"

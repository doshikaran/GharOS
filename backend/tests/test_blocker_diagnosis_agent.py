"""Tests for A23 Blocker Diagnosis Agent
(`app.agents.intention_action.blocker_diagnosis_agent`).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- Blocker diagnosed to a specific type with rationale — a real, explicit,
  human-readable `diagnosis_text`, never buried in a confidence score.
- The six-type taxonomy is closed — an unrecognised type is rejected, not
  silently accepted.
- Re-diagnosis genuinely reconsiders the prior diagnosis.
- Forbidden: unblocking — no tool of any kind.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import ast
import inspect
import json
import types

import pytest
from contracts.graph_types import NodeId

from app.agents.intention_action import blocker_diagnosis_agent
from app.agents.intention_action.blocker_diagnosis_agent import AGENT_ID, BlockerDiagnosisAgent
from app.agents.intention_action.errors import ModelResponseMalformed
from app.agents.intention_action.types import BlockerDiagnosisRequest, BlockerType
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(texts: list[str] | None = None) -> BlockerDiagnosisAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return BlockerDiagnosisAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _request(*, prior_diagnosis: object | None = None) -> BlockerDiagnosisRequest:
    return BlockerDiagnosisRequest(
        obligation_id=NodeId("obligation-dentist"),
        person_id=NodeId("person-aarav"),
        obligation_title="call the dentist",
        obligation_type="health",
        status="derived",
        effort_estimate_minutes=15,
        due_at=None,
        must_start_by=None,
        known_facts=("clinic is only open 9am-5pm weekdays", "phone number not on file"),
        friction_profile_summary=None,
        prior_diagnosis=prior_diagnosis,  # type: ignore[arg-type]
    )


class TestDiagnosis:
    def test_returns_explicit_human_readable_diagnosis(self) -> None:
        response = json.dumps(
            {
                "blocker_type": "aversion",
                "diagnosis_text": "This is blocked because Aarav avoids phone calls, not missing info.",
                "evidence": ["clinic is only open 9am-5pm weekdays"],
                "considered_alternative_types": ["information", "window"],
                "confidence": 0.8,
            }
        )
        agent = _agent(texts=[response])

        diagnosis = agent.diagnose(_request())

        assert diagnosis.blocker_type is BlockerType.AVERSION
        assert diagnosis.diagnosis_text.startswith("This is blocked because Aarav avoids")
        assert diagnosis.considered_alternative_types == (BlockerType.INFORMATION, BlockerType.WINDOW)
        assert diagnosis.is_rediagnosis is False
        assert diagnosis.superseded_diagnosis_type is None
        assert diagnosis.model_tier == "pro"

    def test_unrecognised_blocker_type_rejected(self) -> None:
        response = json.dumps(
            {
                "blocker_type": "laziness",
                "diagnosis_text": "n/a",
                "evidence": [],
                "considered_alternative_types": [],
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.diagnose(_request())

    def test_blank_diagnosis_text_rejected(self) -> None:
        response = json.dumps(
            {
                "blocker_type": "information",
                "diagnosis_text": "   ",
                "evidence": [],
                "considered_alternative_types": [],
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.diagnose(_request())

    def test_alternative_type_repeating_chosen_type_rejected(self) -> None:
        response = json.dumps(
            {
                "blocker_type": "information",
                "diagnosis_text": "n/a",
                "evidence": [],
                "considered_alternative_types": ["information"],
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.diagnose(_request())


class TestRediagnosis:
    def test_rediagnosis_confirming_prior_type_has_no_superseded_type(self) -> None:
        prior = _make_diagnosis(blocker_type=BlockerType.AVERSION)
        response = json.dumps(
            {
                "blocker_type": "aversion",
                "diagnosis_text": "Still an aversion blocker — the pre-drafted message was never sent.",
                "evidence": [],
                "considered_alternative_types": [],
                "confidence": 0.7,
            }
        )
        agent = _agent(texts=[response])

        diagnosis = agent.diagnose(_request(prior_diagnosis=prior))

        assert diagnosis.is_rediagnosis is True
        assert diagnosis.superseded_diagnosis_type is None

    def test_rediagnosis_reaching_a_different_type_records_supersession(self) -> None:
        prior = _make_diagnosis(blocker_type=BlockerType.AVERSION)
        response = json.dumps(
            {
                "blocker_type": "information",
                "diagnosis_text": "Actually the number was never obtained — an information blocker.",
                "evidence": [],
                "considered_alternative_types": ["aversion"],
                "confidence": 0.75,
            }
        )
        agent = _agent(texts=[response])

        diagnosis = agent.diagnose(_request(prior_diagnosis=prior))

        assert diagnosis.is_rediagnosis is True
        assert diagnosis.superseded_diagnosis_type is BlockerType.AVERSION
        assert diagnosis.blocker_type is BlockerType.INFORMATION


def _make_diagnosis(*, blocker_type: BlockerType) -> object:
    from datetime import UTC, datetime

    from app.agents.intention_action.types import BlockerDiagnosis

    return BlockerDiagnosis(
        obligation_id=NodeId("obligation-dentist"),
        person_id=NodeId("person-aarav"),
        blocker_type=blocker_type,
        diagnosis_text="prior diagnosis text",
        evidence=(),
        confidence=0.7,
        considered_alternative_types=(),
        is_rediagnosis=False,
        superseded_diagnosis_type=None,
        model_tier="pro",
        prompt_version="v1",
        invocation_id="inv-1",
        diagnosed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _references_any_tool_machinery(module: types.ModuleType) -> bool:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
            "graph_write_tool" in node.module
            or "graph_read_tool" in node.module
            or ".registry" in node.module
            or "arbitration" in node.module
        ):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.9 A23 forbidden list: 'unblocking' — no search, no draft,
    no write, no read tool of any kind."""

    def test_module_has_no_tool_import(self) -> None:
        assert not _references_any_tool_machinery(blocker_diagnosis_agent)


def test_agent_id_is_a23() -> None:
    assert str(AGENT_ID) == "A23"

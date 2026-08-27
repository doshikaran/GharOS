"""Tests for A26 Slippage Analyst
(`app.agents.intention_action.slippage_analyst_agent`).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- Repeat slippage escalates with real options — never a vague "this keeps
  failing" message.
- Exactly N=3 attempts triggers escalation; fewer re-diagnoses without
  escalating.
- Escalation options are always exactly drop/delegate/pay, grounded in
  real eligible delegates and a real market-rate hint (never fabricated).

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import NodeId

from app.agents.intention_action.blocker_diagnosis_agent import AGENT_ID as A23_ID
from app.agents.intention_action.errors import ModelResponseMalformed
from app.agents.intention_action.slippage_analyst_agent import AGENT_ID, SlippageAnalystAgent
from app.agents.intention_action.types import (
    BlockerDiagnosis,
    BlockerType,
    DelegateCandidate,
    EscalationOptionKind,
    SlippageAnalysisRequest,
    UnblockingAttempt,
)
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(texts: list[str] | None = None) -> SlippageAnalystAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return SlippageAnalystAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _diagnosis(*, blocker_type: BlockerType) -> BlockerDiagnosis:
    return BlockerDiagnosis(
        obligation_id=NodeId("obligation-dentist"),
        person_id=NodeId("person-aarav"),
        blocker_type=blocker_type,
        diagnosis_text="diagnosis text",
        evidence=(),
        confidence=0.7,
        considered_alternative_types=(),
        is_rediagnosis=False,
        superseded_diagnosis_type=None,
        model_tier="pro",
        prompt_version="v1",
        invocation_id="inv",
        diagnosed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _attempt(n: int, *, blocker_type: BlockerType) -> UnblockingAttempt:
    return UnblockingAttempt(
        attempt_number=n,
        diagnosis=_diagnosis(blocker_type=blocker_type),
        action_taken=f"attempt {n} action",
        outcome="failed",
        attempted_at=datetime(2026, 8, n, tzinfo=UTC),
    )


def _priya_delegate() -> DelegateCandidate:
    return DelegateCandidate(
        person_id=NodeId("person-priya"), display_name="Priya", relevant_capability_note="no aversion"
    )


def _request(
    *,
    attempts: tuple[UnblockingAttempt, ...],
    eligible_delegates: tuple[DelegateCandidate, ...] = (),
    market_rate_hint: str | None = None,
) -> SlippageAnalysisRequest:
    return SlippageAnalysisRequest(
        obligation_id=NodeId("obligation-dentist"),
        person_id=NodeId("person-aarav"),
        obligation_title="call the dentist",
        attempts=attempts,
        eligible_delegates=eligible_delegates,
        market_rate_hint=market_rate_hint,
    )


class TestBelowRediagnosisThreshold:
    def test_single_failed_attempt_neither_rediagnoses_nor_escalates(self) -> None:
        agent = _agent()
        request = _request(attempts=(_attempt(1, blocker_type=BlockerType.AVERSION),))

        result = agent.analyze(request)

        assert result.re_diagnosis is None
        assert result.escalation_triggered is False
        assert result.escalation_options == ()


class TestRediagnosisWithoutEscalation:
    def test_two_attempts_rediagnoses_but_does_not_escalate(self) -> None:
        response = json.dumps(
            {
                "re_diagnosis": {
                    "likely_blocker_type": "information",
                    "reasoning": "the modality switch didn't work — the real issue is the missing number",
                    "confidence": 0.7,
                    "changed_from_prior": True,
                },
                "escalation_options": [],
                "message_text": "This has slipped twice — reconsidering the real blocker.",
                "confidence": 0.7,
            }
        )
        agent = _agent(texts=[response])
        request = _request(
            attempts=(
                _attempt(1, blocker_type=BlockerType.AVERSION),
                _attempt(2, blocker_type=BlockerType.AVERSION),
            )
        )

        result = agent.analyze(request)

        assert result.escalation_triggered is False
        assert result.escalation_options == ()
        assert result.re_diagnosis is not None
        assert result.re_diagnosis.likely_blocker_type is BlockerType.INFORMATION
        assert result.re_diagnosis.changed_from_prior is True


class TestEscalationAtThreshold:
    def _escalation_response(self, *, candidate_person_id: str | None, estimated_cost: object) -> str:
        return json.dumps(
            {
                "re_diagnosis": {
                    "likely_blocker_type": "aversion",
                    "reasoning": "still aversion — nothing else explains three failed attempts",
                    "confidence": 0.6,
                    "changed_from_prior": False,
                },
                "escalation_options": [
                    {"kind": "drop", "description": "Drop the dentist visit obligation entirely."},
                    {
                        "kind": "delegate",
                        "description": "Priya can call instead — she does not avoid phone calls.",
                        "candidate_person_id": candidate_person_id,
                    },
                    {
                        "kind": "pay",
                        "description": "A concierge service could book this for a fee.",
                        "estimated_cost": estimated_cost,
                    },
                ],
                "message_text": "This has slipped 3 times — drop, delegate, or pay someone to handle it?",
                "confidence": 0.75,
            }
        )

    def test_third_attempt_triggers_escalation_with_three_real_options(self) -> None:
        response = self._escalation_response(candidate_person_id="person-priya", estimated_cost=None)
        agent = _agent(texts=[response])
        request = _request(
            attempts=(
                _attempt(1, blocker_type=BlockerType.AVERSION),
                _attempt(2, blocker_type=BlockerType.AVERSION),
                _attempt(3, blocker_type=BlockerType.AVERSION),
            ),
            eligible_delegates=(_priya_delegate(),),
        )

        result = agent.analyze(request)

        assert result.escalation_triggered is True
        assert result.attempt_count == 3
        assert result.threshold == 3
        assert {opt.kind for opt in result.escalation_options} == {
            EscalationOptionKind.DROP,
            EscalationOptionKind.DELEGATE,
            EscalationOptionKind.PAY,
        }
        assert result.message_text != ""

    def test_delegate_option_naming_a_non_eligible_person_is_rejected(self) -> None:
        response = self._escalation_response(candidate_person_id="person-ghost", estimated_cost=None)
        agent = _agent(texts=[response])
        request = _request(
            attempts=tuple(_attempt(n, blocker_type=BlockerType.AVERSION) for n in (1, 2, 3)),
            eligible_delegates=(_priya_delegate(),),
        )

        with pytest.raises(ModelResponseMalformed):
            agent.analyze(request)

    def test_pay_estimated_cost_dropped_when_no_market_rate_hint_given(self) -> None:
        """Never trust a fabricated figure this module has no grounding
        for — even if the model returns one."""
        response = self._escalation_response(candidate_person_id=None, estimated_cost=1500.0)
        agent = _agent(texts=[response])
        request = _request(
            attempts=tuple(_attempt(n, blocker_type=BlockerType.AVERSION) for n in (1, 2, 3)),
            market_rate_hint=None,
        )

        result = agent.analyze(request)

        pay_option = next(opt for opt in result.escalation_options if opt.kind is EscalationOptionKind.PAY)
        assert pay_option.estimated_cost is None

    def test_pay_estimated_cost_kept_when_real_market_rate_hint_given(self) -> None:
        response = self._escalation_response(candidate_person_id=None, estimated_cost=1500.0)
        agent = _agent(texts=[response])
        request = _request(
            attempts=tuple(_attempt(n, blocker_type=BlockerType.AVERSION) for n in (1, 2, 3)),
            market_rate_hint="concierge appointment-booking services typically charge ₹1000-2000",
        )

        result = agent.analyze(request)

        pay_option = next(opt for opt in result.escalation_options if opt.kind is EscalationOptionKind.PAY)
        assert pay_option.estimated_cost == 1500.0

    def test_missing_a_required_option_kind_is_rejected(self) -> None:
        response = json.dumps(
            {
                "re_diagnosis": {
                    "likely_blocker_type": "aversion",
                    "reasoning": "n/a",
                    "confidence": 0.5,
                    "changed_from_prior": False,
                },
                "escalation_options": [
                    {"kind": "drop", "description": "drop it"},
                    {"kind": "delegate", "description": "delegate it", "candidate_person_id": None},
                ],
                "message_text": "n/a",
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])
        request = _request(attempts=tuple(_attempt(n, blocker_type=BlockerType.AVERSION) for n in (1, 2, 3)))

        with pytest.raises(ModelResponseMalformed):
            agent.analyze(request)


def test_agent_id_is_a26() -> None:
    assert str(AGENT_ID) == "A26"


def test_a23_id_import_sanity() -> None:
    """Sanity check the fixture builder above references the real A23
    diagnosis shape, not a stand-in."""
    assert str(A23_ID) == "A23"

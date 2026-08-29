"""Tests for A67 Voice Intent Classifier
(`app.agents.voice.voice_intent_classifier_agent`).

Covers: a real R0-through-R4 intent-classification sweep (spec §14.5's
seven-class table), the structural `decision_trigger` -> R4 rule (never
taken from the model), rejection of an out-of-range `command`/`approval`
risk tier, and the deterministic `_requires_confirmation` read-back rule
(spec §14.6's five mandatory cases) exercised both through the full agent
and directly as a pure function.
"""

from __future__ import annotations

import json

import pytest
from contracts.actions import RiskTier
from contracts.graph_types import NodeId

from app.agents.voice.errors import ModelResponseMalformed
from app.agents.voice.types import (
    NormalizedSpan,
    SpeakerLanguageContext,
    VoiceIntentClass,
    VoiceIntentRequest,
)
from app.agents.voice.voice_intent_classifier_agent import (
    AGENT_ID,
    VoiceIntentClassifierAgent,
    _ConfirmationSignals,
    _requires_confirmation,
)
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import PRO_TIER_ALLOWLIST

from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str]) -> VoiceIntentClassifierAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return VoiceIntentClassifierAgent(gemini_client=client)


def _speaker() -> SpeakerLanguageContext:
    return SpeakerLanguageContext(person_id=NodeId("person-1"), language_profile=None)


def _plain_span(text: str, *, kind: str = "plain") -> NormalizedSpan:
    return NormalizedSpan(
        original_text=text,
        normalized_text=text,
        kind=kind,  # type: ignore[arg-type]
        language="en",
        start_char=0,
        end_char=len(text),
    )


def _request(*, raw_text: str, spans: tuple[NormalizedSpan, ...] = ()) -> VoiceIntentRequest:
    return VoiceIntentRequest(turn_id="turn-1", raw_text=raw_text, normalized_spans=spans, speaker=_speaker())


def _response(
    *,
    intent: str,
    risk_tier: str | None = None,
    involves_hard_constraint_name: bool = False,
    involves_staff_attendance_or_salary: bool = False,
) -> str:
    payload: dict[str, object] = {
        "intent": intent,
        "target_summary": "a real turn",
        "reasoning": "test reasoning",
        "confidence": 0.9,
        "involves_hard_constraint_name": involves_hard_constraint_name,
        "involves_staff_attendance_or_salary": involves_staff_attendance_or_salary,
    }
    if risk_tier is not None:
        payload["risk_tier"] = risk_tier
    return json.dumps(payload)


class TestFullIntentSweepR0ThroughR4:
    def test_capture_has_no_risk_tier(self) -> None:
        agent = _agent(texts=[_response(intent="capture")])
        result = agent.classify(_request(raw_text="Aarav has a field trip Friday"))
        assert result.intent is VoiceIntentClass.CAPTURE
        assert result.risk_tier is None

    def test_intention_has_no_risk_tier(self) -> None:
        agent = _agent(texts=[_response(intent="intention")])
        result = agent.classify(_request(raw_text="Remind me to call the plumber"))
        assert result.intent is VoiceIntentClass.INTENTION
        assert result.risk_tier is None

    def test_query_has_no_risk_tier(self) -> None:
        agent = _agent(texts=[_response(intent="query")])
        result = agent.classify(_request(raw_text="Did we pay the society dues?"))
        assert result.intent is VoiceIntentClass.QUERY
        assert result.risk_tier is None

    def test_command_resolves_to_r0(self) -> None:
        agent = _agent(texts=[_response(intent="command", risk_tier="R0")])
        result = agent.classify(_request(raw_text="Mark the maid absent today"))
        assert result.intent is VoiceIntentClass.COMMAND
        assert result.risk_tier is RiskTier.R0_SILENT

    def test_command_resolves_to_r1(self) -> None:
        agent = _agent(texts=[_response(intent="command", risk_tier="R1")])
        result = agent.classify(_request(raw_text="Add milk to the shopping list"))
        assert result.risk_tier is RiskTier.R1_NOTIFY

    def test_approval_resolves_to_r2(self) -> None:
        agent = _agent(texts=[_response(intent="approval", risk_tier="R2")])
        result = agent.classify(_request(raw_text="Yes, send that message"))
        assert result.intent is VoiceIntentClass.APPROVAL
        assert result.risk_tier is RiskTier.R2_APPROVE
        assert result.requires_confirmation is True

    def test_approval_resolves_to_r3(self) -> None:
        agent = _agent(texts=[_response(intent="approval", risk_tier="R3")])
        result = agent.classify(_request(raw_text="Yes, pay the society dues"))
        assert result.risk_tier is RiskTier.R3_EXPLICIT_APPROVE
        assert result.requires_confirmation is True

    def test_decision_trigger_is_always_r4_regardless_of_model_output(self) -> None:
        """spec §14.5: "R4 decisions are never resolved by voice" — the
        model's own opinion on the tier is irrelevant by design."""
        agent = _agent(texts=[_response(intent="decision_trigger", risk_tier="R1")])
        result = agent.classify(_request(raw_text="Should we buy a car?"))
        assert result.intent is VoiceIntentClass.DECISION_TRIGGER
        assert result.risk_tier is RiskTier.R4_ESCALATE_ONLY

    def test_correction_has_no_risk_tier(self) -> None:
        agent = _agent(texts=[_response(intent="correction")])
        result = agent.classify(_request(raw_text="No, that's Kaku not Baba"))
        assert result.intent is VoiceIntentClass.CORRECTION
        assert result.risk_tier is None


class TestRiskTierValidation:
    def test_command_with_out_of_range_tier_raises(self) -> None:
        agent = _agent(texts=[_response(intent="command", risk_tier="R3")])
        with pytest.raises(ModelResponseMalformed):
            agent.classify(_request(raw_text="Mark the maid absent today"))

    def test_approval_with_out_of_range_tier_raises(self) -> None:
        agent = _agent(texts=[_response(intent="approval", risk_tier="R0")])
        with pytest.raises(ModelResponseMalformed):
            agent.classify(_request(raw_text="Yes, do it"))

    def test_unknown_intent_raises(self) -> None:
        agent = _agent(texts=[_response(intent="not-a-real-intent")])
        with pytest.raises(ModelResponseMalformed):
            agent.classify(_request(raw_text="whatever"))


class TestRequiresConfirmationDeterministicRule:
    """spec §14.6's five mandatory-read-back cases, exercised directly as
    a pure function — independent of prompt wording."""

    def _signals(self, **overrides: object) -> _ConfirmationSignals:
        base: dict[str, object] = {
            "intent": VoiceIntentClass.CAPTURE,
            "risk_tier": None,
            "has_amount_span": False,
            "has_committing_date_span": False,
            "involves_hard_constraint_name": False,
            "involves_staff_attendance_or_salary": False,
        }
        base.update(overrides)
        return _ConfirmationSignals(**base)  # type: ignore[arg-type]

    def test_amount_always_requires_confirmation(self) -> None:
        assert _requires_confirmation(self._signals(has_amount_span=True)) is True

    def test_hard_constraint_name_requires_confirmation(self) -> None:
        assert _requires_confirmation(self._signals(involves_hard_constraint_name=True)) is True

    def test_staff_attendance_or_salary_requires_confirmation(self) -> None:
        assert _requires_confirmation(self._signals(involves_staff_attendance_or_salary=True)) is True

    def test_r2_approval_requires_confirmation(self) -> None:
        signals = self._signals(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R2_APPROVE)
        assert _requires_confirmation(signals) is True

    def test_r3_approval_requires_confirmation(self) -> None:
        signals = self._signals(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R3_EXPLICIT_APPROVE)
        assert _requires_confirmation(signals) is True

    def test_committing_date_on_command_requires_confirmation(self) -> None:
        signals = self._signals(intent=VoiceIntentClass.COMMAND, has_committing_date_span=True)
        assert _requires_confirmation(signals) is True

    def test_date_on_mere_capture_does_not_require_confirmation(self) -> None:
        """A `capture` turn mentioning a date ("field trip Friday") is not
        itself "committing to" anything by voice — the full pipeline
        handles it downstream with its own review, not a voice read-back."""
        signals = self._signals(intent=VoiceIntentClass.CAPTURE, has_committing_date_span=True)
        assert _requires_confirmation(signals) is False

    def test_plain_command_with_no_signals_does_not_require_confirmation(self) -> None:
        signals = self._signals(intent=VoiceIntentClass.COMMAND, risk_tier=RiskTier.R0_SILENT)
        assert _requires_confirmation(signals) is False

    def test_amount_span_forces_confirmation_through_full_agent(self) -> None:
        agent = _agent(texts=[_response(intent="capture")])
        result = agent.classify(
            _request(raw_text="pay 500 rupees", spans=(_plain_span("500 rupees", kind="amount"),))
        )
        assert result.requires_confirmation is True


def test_agent_id_is_a67() -> None:
    assert str(AGENT_ID) == "A67"


def test_a67_is_on_pro_tier_allowlist() -> None:
    assert AGENT_ID in PRO_TIER_ALLOWLIST

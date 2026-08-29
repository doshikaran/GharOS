"""Tests for A68 Confirmation Agent (`app.agents.voice.confirmation_agent`).

Covers: `generate_readback`'s structural amount/name substring checks,
and `evaluate_response`'s three-way silence / ambiguous-reply / explicit-
affirmative behaviour — including the adversarial case where a fake model
response smuggles a bogus `"confirmed": true` key alongside a genuine
`"genuinely_affirmative": false`, the `GeminiCallFailed` fail-closed path,
and the structural proof that `ConfirmationResult` can never itself be
read as an authorisation to act (spec §14.6 rule 4 / rule 6, ADR-020
Decision 5 item 3).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from app.agents.voice import confirmation_agent
from app.agents.voice.confirmation_agent import AGENT_ID, ConfirmationAgent
from app.agents.voice.errors import ModelResponseMalformed
from app.agents.voice.types import (
    ConfirmationEvaluationRequest,
    ConfirmationResult,
    NameReference,
    NormalizedSpan,
    ReadbackRequest,
    VoiceIntentClass,
    VoiceIntentResult,
)
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import PRO_TIER_ALLOWLIST

from ._gemini_fakes import FakeModels, fake_router


def _agent_and_fake(*, texts: list[str]) -> tuple[ConfirmationAgent, FakeModels]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    return ConfirmationAgent(gemini_client=client), fake_models


def _amount_span(*, original: str, value: float, display: str) -> NormalizedSpan:
    return NormalizedSpan(
        original_text=original,
        normalized_text=original,
        kind="amount",
        language="hi",
        start_char=0,
        end_char=len(original),
        amount_value=value,
        amount_display=display,
    )


def _intent_result(*, requires_confirmation: bool = True) -> VoiceIntentResult:
    from datetime import UTC, datetime

    return VoiceIntentResult(
        turn_id="turn-1",
        intent=VoiceIntentClass.APPROVAL,
        risk_tier=None,
        target_summary="pay society dues",
        requires_confirmation=requires_confirmation,
        reasoning="test",
        confidence=0.9,
        model_tier="pro",
        prompt_version="v1",
        invocation_id="inv-1",
        classified_at=datetime.now(UTC),
    )


class TestGenerateReadbackStructuralChecks:
    def test_readback_containing_required_amount_and_name_passes(self) -> None:
        readback_text = (
            "Confirming: pay ₹3,500 — three thousand five hundred — to Aarav, your son. Shall I proceed?"
        )
        agent, _ = _agent_and_fake(texts=[json.dumps({"readback_text": readback_text, "confidence": 0.95})])
        request = ReadbackRequest(
            turn_id="turn-1",
            intent=_intent_result(),
            amount_spans=(_amount_span(original="saade teen hazaar", value=3500, display="₹3,500"),),
            name_references=(NameReference(display_name="Aarav", relationship_to_speaker="your son"),),
            date_spans=(),
            speaker_language="en",
        )

        result = agent.generate_readback(request)

        assert "₹3,500" in result.readback_text
        assert result.requires_affirmative is True
        assert result.model_tier == "pro"

    def test_readback_missing_required_amount_raises(self) -> None:
        agent, _ = _agent_and_fake(
            texts=[json.dumps({"readback_text": "Shall I proceed with the payment?", "confidence": 0.9})]
        )
        request = ReadbackRequest(
            turn_id="turn-1",
            intent=_intent_result(),
            amount_spans=(_amount_span(original="saade teen hazaar", value=3500, display="₹3,500"),),
            name_references=(),
            date_spans=(),
            speaker_language="en",
        )
        with pytest.raises(ModelResponseMalformed):
            agent.generate_readback(request)

    def test_readback_missing_required_name_relationship_raises(self) -> None:
        agent, _ = _agent_and_fake(
            texts=[json.dumps({"readback_text": "Confirming for Aarav. Shall I proceed?", "confidence": 0.9})]
        )
        request = ReadbackRequest(
            turn_id="turn-1",
            intent=_intent_result(),
            amount_spans=(),
            name_references=(NameReference(display_name="Aarav", relationship_to_speaker="your son"),),
            date_spans=(),
            speaker_language="en",
        )
        with pytest.raises(ModelResponseMalformed):
            agent.generate_readback(request)


class TestEvaluateResponseSilenceAmbiguousAffirmative:
    def test_silence_none_is_never_confirmed_and_makes_no_model_call(self) -> None:
        agent, fake_models = _agent_and_fake(texts=["should never be reached"])
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I proceed?",
            spoken_response_text=None,
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False
        assert result.model_tier == "deterministic"
        assert fake_models.calls == []

    def test_silence_empty_string_is_never_confirmed_and_makes_no_model_call(self) -> None:
        agent, fake_models = _agent_and_fake(texts=["should never be reached"])
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I proceed?",
            spoken_response_text="   ",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False
        assert fake_models.calls == []

    def test_ambiguous_reply_is_never_confirmed_and_makes_no_model_call(self) -> None:
        agent, fake_models = _agent_and_fake(texts=["should never be reached"])
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I proceed?",
            spoken_response_text="pata nahi, shayad",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False
        assert result.matched_affirmative_phrase is None
        assert fake_models.calls == []

    def test_explicit_affirmative_confirmed_by_semantic_check(self) -> None:
        agent, _ = _agent_and_fake(
            texts=[json.dumps({"genuinely_affirmative": True, "explanation": "unqualified yes"})]
        )
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I pay ₹3,500 — three thousand five hundred?",
            spoken_response_text="haan kar do",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is True
        assert result.matched_affirmative_phrase is not None
        assert result.model_tier == "pro"

    def test_matched_token_inside_hedge_is_narrowed_to_not_confirmed(self) -> None:
        """ "haan, lekin abhi nahi" ("yes, but not right now") matches the
        "haan" token but is not a genuine affirmative — the semantic check
        must narrow this to `confirmed=False`."""
        agent, _ = _agent_and_fake(
            texts=[json.dumps({"genuinely_affirmative": False, "explanation": "deferred, not confirmed"})]
        )
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I pay ₹3,500?",
            spoken_response_text="haan, lekin abhi nahi",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False
        assert result.matched_affirmative_phrase is not None  # a token DID match structurally

    def test_smuggled_confirmed_key_is_never_read(self) -> None:
        """Adversarial case: the fake model response includes a bogus
        `"confirmed": true` key alongside a genuine `"genuinely_
        affirmative": false` — the final result must still be
        `confirmed=False`, proving this module never reads a `"confirmed"`
        key out of parsed model JSON at all."""
        agent, _ = _agent_and_fake(
            texts=[
                json.dumps(
                    {"confirmed": True, "genuinely_affirmative": False, "explanation": "actually a hedge"}
                )
            ]
        )
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I pay ₹3,500?",
            spoken_response_text="haan bilkul",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False

    def test_gemini_call_failure_fails_closed_never_confirmed(self) -> None:
        """An empty model response makes `GeminiClient` raise
        `GeminiCallFailed` — caught explicitly here and resolved to
        `confirmed=False`, never propagated as an ambiguous outcome a
        caller might otherwise construe permissively."""
        agent, _ = _agent_and_fake(texts=[""])
        request = ConfirmationEvaluationRequest(
            turn_id="turn-1",
            readback_text="Shall I pay ₹3,500?",
            spoken_response_text="haan bilkul",
            speaker_language="hi",
        )

        result = agent.evaluate_response(request)

        assert result.confirmed is False
        assert result.model_tier == "deterministic"


class TestStructuralNeverAnAuthorisation:
    """`ConfirmationResult` must never itself carry a field a caller could
    mistake for an authorisation to act — see `types.ConfirmationResult`'s
    own docstring and ADR-020 Decision 5 item 3."""

    def test_confirmation_result_field_set_carries_no_authority_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ConfirmationResult)}
        assert field_names == {
            "turn_id",
            "confirmed",
            "reason",
            "matched_affirmative_phrase",
            "model_tier",
            "prompt_version",
            "invocation_id",
            "evaluated_at",
        }

    def test_confirmation_agent_module_never_imports_risk_tier(self) -> None:
        """AST-based, not a raw substring search — the module's own
        docstring legitimately *discusses* `RiskTier` in prose (explaining
        why it holds none); what must be structurally absent is an actual
        import of it."""
        import ast

        module_path = Path(inspect.getfile(confirmation_agent))
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

        imported_names: set[str] = set()
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)

        assert "RiskTier" not in imported_names
        assert "contracts.actions" not in imported_modules


def test_agent_id_is_a68() -> None:
    assert str(AGENT_ID) == "A68"


def test_a68_is_on_pro_tier_allowlist() -> None:
    assert AGENT_ID in PRO_TIER_ALLOWLIST

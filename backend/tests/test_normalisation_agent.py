"""Tests for A65 Normalisation Agent (`app.agents.voice.normalisation_agent`).

Covers: transliteration/date/kinship normalisation with the original text
always retained, a lakh-scale amount, a spoken-amount ("saade teen
hazaar") case, the batched Pro-tier amount-disambiguation escalation path
(both a case it resolves and a case it cannot — "always clarify, never
round or guess"), and malformed-response rejection.
"""

from __future__ import annotations

import json

import pytest

from app.agents.voice.errors import ModelResponseMalformed
from app.agents.voice.normalisation_agent import AGENT_ID, NormalisationAgent
from app.agents.voice.types import LanguageSpan, NormalizationRequest
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import PRO_TIER_ALLOWLIST

from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str]) -> NormalisationAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return NormalisationAgent(gemini_client=client)


def _request(*, raw_text: str) -> NormalizationRequest:
    return NormalizationRequest(
        turn_id="turn-1",
        raw_text=raw_text,
        language_spans=(
            LanguageSpan(
                text=raw_text,
                start_char=0,
                end_char=len(raw_text),
                language="hi",
                confidence=0.9,
                fallback_applied=False,
                ambiguous_between=(),
            ),
        ),
        reference_date="2026-08-29",
    )


class TestPlainDateKinshipNormalisation:
    def test_original_text_always_retained_even_when_unchanged(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "Kaku",
                        "normalized_text": "Kaku",
                        "kind": "kinship",
                        "language": "mr",
                        "start_char": 0,
                        "end_char": 4,
                    }
                ],
                "confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        result = agent.normalize(_request(raw_text="Kaku"))

        span = result.spans[0]
        assert span.original_text == "Kaku"
        assert span.normalized_text == "Kaku"
        assert span.kind == "kinship"
        assert result.model_tier == "flash"

    def test_transliteration_variance_collapses_to_canonical_form(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "nhi",
                        "normalized_text": "nahi",
                        "kind": "plain",
                        "language": "hi",
                        "start_char": 0,
                        "end_char": 3,
                    }
                ],
                "confidence": 0.85,
            }
        )
        agent = _agent(texts=[response])
        result = agent.normalize(_request(raw_text="nhi"))

        span = result.spans[0]
        assert span.original_text == "nhi"
        assert span.normalized_text == "nahi"


class TestUnambiguousAmounts:
    def test_spoken_amount_resolves_and_gets_digit_grouped_display(self) -> None:
        """"saade teen hazaar" = 3,500 — spec §14.2's own worked example."""
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "saade teen hazaar",
                        "normalized_text": "saade teen hazaar",
                        "kind": "amount",
                        "language": "hi",
                        "start_char": 0,
                        "end_char": 17,
                        "amount_value": 3500,
                        "ambiguous": False,
                    }
                ],
                "confidence": 0.93,
            }
        )
        agent = _agent(texts=[response])
        result = agent.normalize(_request(raw_text="saade teen hazaar"))

        span = result.spans[0]
        assert span.amount_value == 3500
        assert span.amount_display == "₹3,500"
        assert span.needs_clarification is False
        assert result.model_tier == "flash"
        assert result.any_needs_clarification is False

    def test_lakh_scale_amount_resolves(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "teen lakh",
                        "normalized_text": "teen lakh",
                        "kind": "amount",
                        "language": "hi",
                        "start_char": 0,
                        "end_char": 9,
                        "amount_value": 300000,
                        "ambiguous": False,
                    }
                ],
                "confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        result = agent.normalize(_request(raw_text="teen lakh"))

        span = result.spans[0]
        assert span.amount_value == 300000
        assert span.amount_display == "₹3,00,000"


class TestAmbiguousAmountEscalation:
    def _flash_flags_ambiguous(self, *, original_text: str) -> str:
        return json.dumps(
            {
                "spans": [
                    {
                        "original_text": original_text,
                        "normalized_text": original_text,
                        "kind": "amount",
                        "language": "hi",
                        "start_char": 0,
                        "end_char": len(original_text),
                        "ambiguous": True,
                    }
                ],
                "confidence": 0.5,
            }
        )

    def test_escalation_resolves_with_real_context(self) -> None:
        original_text = "paanch sau ya cheh sau"
        flash_response = self._flash_flags_ambiguous(original_text=original_text)
        pro_response = json.dumps(
            {
                "resolutions": [
                    {"original_text": original_text, "resolved": True, "amount_value": 500}
                ]
            }
        )
        agent = _agent(texts=[flash_response, pro_response])

        result = agent.normalize(_request(raw_text=original_text))

        span = result.spans[0]
        assert span.amount_value == 500
        assert span.amount_display == "₹500"
        assert span.needs_clarification is False
        assert result.model_tier == "pro"

    def test_escalation_still_ambiguous_never_rounds_or_guesses(self) -> None:
        """"teen-chaar hazaar" ("three-four thousand") is a genuine
        approximate-range idiom, not a single figure — spec §15.11 A65
        failure mode: always clarify, never round or guess."""
        original_text = "teen-chaar hazaar"
        flash_response = self._flash_flags_ambiguous(original_text=original_text)
        pro_response = json.dumps(
            {
                "resolutions": [
                    {
                        "original_text": original_text,
                        "resolved": False,
                        "clarification_reason": "spoken as an approximate range, not a single figure",
                    }
                ]
            }
        )
        agent = _agent(texts=[flash_response, pro_response])

        result = agent.normalize(_request(raw_text=original_text))

        span = result.spans[0]
        assert span.amount_value is None
        assert span.amount_display is None
        assert span.needs_clarification is True
        assert span.clarification_reason == "spoken as an approximate range, not a single figure"
        assert result.any_needs_clarification is True
        assert result.model_tier == "pro"


class TestMalformedResponses:
    def test_invalid_kind_raises(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "x",
                        "normalized_text": "x",
                        "kind": "not-a-real-kind",
                        "language": "en",
                        "start_char": 0,
                        "end_char": 1,
                    }
                ],
                "confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        with pytest.raises(ModelResponseMalformed):
            agent.normalize(_request(raw_text="x"))

    def test_amount_missing_value_when_not_ambiguous_raises(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "original_text": "kuch rupaye",
                        "normalized_text": "kuch rupaye",
                        "kind": "amount",
                        "language": "hi",
                        "start_char": 0,
                        "end_char": 11,
                        "ambiguous": False,
                    }
                ],
                "confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        with pytest.raises(ModelResponseMalformed):
            agent.normalize(_request(raw_text="kuch rupaye"))


def test_agent_id_is_a65() -> None:
    assert str(AGENT_ID) == "A65"


def test_a65_is_on_pro_tier_allowlist_for_amount_escalation_only() -> None:
    assert AGENT_ID in PRO_TIER_ALLOWLIST

"""Tests for A29 Leakage Detection Agent
(`app.agents.ledger.leakage_detection_agent`).

PHASES.md Gate 7's own acceptance list, this module's share of it:
- Silent price hike detected from price history — **differentiated**
  between a hike on a rarely-used vs. a frequently-used commitment (the
  same objective price signal, two different real verdicts, because the
  model reasons over usage too — never a bare rule).
- Unused service flagged with usage evidence.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from contracts.graph_types import NodeId

from app.agents.ledger.errors import ModelResponseMalformed
from app.agents.ledger.leakage_detection_agent import AGENT_ID, LeakageDetectionAgent
from app.agents.ledger.types import LeakageAssessmentRequest
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import NOW

from ._gemini_fakes import FakeModels, fake_router


def _agent(response_obj: dict[str, object]) -> LeakageDetectionAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return LeakageDetectionAgent(gemini_client=client)


def _request(
    *,
    price_history: tuple[tuple[datetime, float], ...],
    last_used_at: datetime | None,
    priorities: str = "keeping essentials, cutting anything unused",
) -> LeakageAssessmentRequest:
    return LeakageAssessmentRequest(
        commitment_id=NodeId("commitment-1"),
        label="City Gym membership",
        counterparty="City Gym Pvt Ltd",
        amount=1500.0,
        cadence="monthly",
        price_history=price_history,
        last_used_at=last_used_at,
        status="active",
        household_priorities=priorities,
        now=NOW,
    )


class TestPriceHikeDifferentiatedByUsage:
    """The same objective price-history signal (a hike from 1200 -> 1500),
    on a frequently-used vs. a rarely-used commitment — the model's real
    verdict differs because it reasons over the usage signal, never a
    fixed cutoff this module applies itself."""

    _HIKE_HISTORY = ((NOW - timedelta(days=365), 1200.0), (NOW - timedelta(days=30), 1500.0))

    def test_hike_on_frequently_used_commitment_is_worth_keeping(self) -> None:
        agent = _agent(
            {
                "verdict": "worth_keeping",
                "confidence": 0.85,
                "reasoning": "used 3x/week, well within priorities",
            }
        )
        request = _request(price_history=self._HIKE_HISTORY, last_used_at=NOW - timedelta(days=1))

        finding = agent.assess(request)

        assert finding.verdict == "worth_keeping"
        assert finding.days_since_last_used == 1
        assert finding.price_change_pct is not None
        assert finding.price_change_pct == pytest.approx(25.0)
        assert finding.evidence["days_since_last_used"] == "1"

    def test_same_hike_on_rarely_used_commitment_is_leakage(self) -> None:
        agent = _agent(
            {
                "verdict": "leakage",
                "confidence": 0.9,
                "reasoning": "not used in over 5 months despite a price hike",
            }
        )
        request = _request(price_history=self._HIKE_HISTORY, last_used_at=NOW - timedelta(days=160))

        finding = agent.assess(request)

        assert finding.verdict == "leakage"
        assert finding.days_since_last_used == 160
        assert finding.price_change_pct == pytest.approx(25.0)


class TestUnusedServiceFlagged:
    def test_never_used_service_flagged_with_usage_evidence(self) -> None:
        agent = _agent(
            {
                "verdict": "leakage",
                "confidence": 0.95,
                "reasoning": "never used since signup, no matching priority",
            }
        )
        request = _request(
            price_history=(), last_used_at=None, priorities="focus spend on the kids' school needs"
        )

        finding = agent.assess(request)

        assert finding.verdict == "leakage"
        assert finding.days_since_last_used is None
        assert finding.evidence["last_used_at"] == "never"
        assert finding.price_change_pct is None


class TestNeverARuleBasedCutoff:
    def test_the_module_never_computes_a_verdict_itself(self) -> None:
        """The verdict returned always comes from the (fake) model's own
        response — proven by asserting an *unexpected* verdict for a
        commitment that a naive rule would call obviously safe (used
        yesterday) still comes back exactly as the model said, never
        overridden by this module's own logic."""
        agent = _agent(
            {
                "verdict": "ambiguous",
                "confidence": 0.4,
                "reasoning": "recent use, but household flagged general cost-cutting",
            }
        )
        request = _request(price_history=(), last_used_at=NOW - timedelta(days=1))

        finding = agent.assess(request)

        assert finding.verdict == "ambiguous"


class TestMalformedVerdictRejected:
    def test_unrecognised_verdict_raises(self) -> None:
        agent = _agent({"verdict": "cancel_it", "confidence": 0.5, "reasoning": "n/a"})
        request = _request(price_history=(), last_used_at=None)

        with pytest.raises(ModelResponseMalformed):
            agent.assess(request)


def test_agent_id_is_a29() -> None:
    assert str(AGENT_ID) == "A29"

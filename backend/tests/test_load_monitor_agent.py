"""Tests for A21 Load Monitor (`app.agents.fair_allocator.load_monitor_agent`).

PHASES.md Phase 8's own acceptance list, this module's share of it:
- No observed load at all -> "insufficient_data", never a guessed
  imbalance.
- Drift within the threshold -> "balanced", deterministic, no model call.
- Drift beyond the threshold -> "creeping_imbalance", narrated (Flash)
  using only the real, already-computed numbers.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from contracts.graph_types import NodeId

from app.agents.fair_allocator.load_monitor_agent import AGENT_ID, LoadMonitorAgent
from app.agents.fair_allocator.types import LoadDriftCheckRequest
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
_WINDOW = (_NOW - timedelta(days=30), _NOW)


def _agent(texts: list[str] | None = None) -> tuple[LoadMonitorAgent, FakeModels]:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    client = GeminiClient(router=fake_router(fake_models))
    return LoadMonitorAgent(gemini_client=client), fake_models


class TestInsufficientData:
    def test_zero_household_load_never_guesses_an_imbalance(self) -> None:
        agent, fake_models = _agent()
        request = LoadDriftCheckRequest(
            person_id=NodeId("person-priya"),
            window=_WINDOW,
            expected_share_of_total_cost=0.5,
            observed_load=0.0,
            household_total_observed_load=0.0,
        )

        finding = agent.check_drift(request)

        assert finding.verdict == "insufficient_data"
        assert finding.observed_share is None
        assert finding.drift is None
        assert finding.model_tier == "deterministic"
        assert len(fake_models.calls) == 0


class TestBalanced:
    def test_small_drift_is_balanced_with_no_model_call(self) -> None:
        agent, fake_models = _agent()
        request = LoadDriftCheckRequest(
            person_id=NodeId("person-priya"),
            window=_WINDOW,
            expected_share_of_total_cost=0.5,
            observed_load=52.0,
            household_total_observed_load=100.0,
        )

        finding = agent.check_drift(request)

        assert finding.verdict == "balanced"
        assert finding.observed_share == 0.52
        assert finding.model_tier == "deterministic"
        assert len(fake_models.calls) == 0


class TestCreepingImbalance:
    def test_large_drift_is_flagged_and_narrated(self) -> None:
        narration_text = "Priya is now doing 80% of completed load against an intended 50% share."
        response = json.dumps({"reasoning": narration_text, "confidence": 0.9})
        agent, fake_models = _agent(texts=[response])
        request = LoadDriftCheckRequest(
            person_id=NodeId("person-priya"),
            window=_WINDOW,
            expected_share_of_total_cost=0.5,
            observed_load=80.0,
            household_total_observed_load=100.0,
        )

        finding = agent.check_drift(request)

        assert finding.verdict == "creeping_imbalance"
        assert finding.observed_share == 0.8
        assert finding.drift == pytest.approx(0.3)
        assert finding.model_tier == "flash"
        assert finding.reasoning == narration_text
        assert len(fake_models.calls) == 1


def test_agent_id_is_a21() -> None:
    assert str(AGENT_ID) == "A21"

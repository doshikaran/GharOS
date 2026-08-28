"""Tests for A56 Fallback Coordinator
(`app.agents.concierge.fallback_coordinator_agent`).

Gate 10's own acceptance list this file's share of: "failure ladder ends
in useful human escalation" — three failed/needs-callback attempts
retry-then-escalate on a real, documented backoff, and the web-booking
fallback is never returned this phase (an honest no-op). The actual
`EscalationAgent.route()` call is proven separately, in
`test_concierge_fallback_dispatcher.py` — this module proves only
`FallbackCoordinatorAgent`'s own decision, which holds zero import path
into `app.arbitration` (see that module's own docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from contracts.actions import RiskTier
from contracts.graph_types import NodeId

from app.agents.concierge.fallback_coordinator_agent import AGENT_ID, FallbackCoordinatorAgent
from app.agents.concierge.types import CallOutcomeReport, FallbackAction, FallbackEscalationPayload

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _coordinator() -> FallbackCoordinatorAgent:
    return FallbackCoordinatorAgent()


def _needs_callback_outcome(
    summary: str = "Clinic asked something outside disclosable facts.",
) -> CallOutcomeReport:
    return CallOutcomeReport(
        call_id="call-1",
        target_provider_id=NodeId("provider-1"),
        transcript_source_document_id=NodeId("doc-1"),
        disclosure_given=True,
        claimed_slot=None,
        claimed_outcome_summary=summary,
        out_of_bounds_encountered=False,
        requires_human_callback=True,
    )


class TestAgentIdentity:
    def test_agent_id_is_a56(self) -> None:
        assert str(AGENT_ID) == "A56"


class TestNeverImportsArbitration:
    def test_module_has_no_app_arbitration_import(self) -> None:
        """Structural proof, not just a docstring claim — mirrors
        `test_action_construction_boundary.py`'s own AST-based rigor at
        the single-module level."""
        import ast
        import inspect

        import app.agents.concierge.fallback_coordinator_agent as module

        source = inspect.getsource(module)
        tree = ast.parse(source)
        imported_modules = [
            alias.name
            for node in ast.walk(tree)
            for alias in (node.names if isinstance(node, ast.Import) else [])
        ] + [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
        assert not any("arbitration" in name for name in imported_modules)


class TestRetryLadder:
    def test_first_attempt_retries_with_a_real_backoff(self) -> None:
        coordinator = _coordinator()
        decision = coordinator.decide(
            outcome=_needs_callback_outcome(),
            failure_reason=None,
            attempt_number=0,
            target_provider_name="Sunrise Dental",
            related_node_id=NodeId("obligation-1"),
            now=NOW,
        )
        assert decision.action is FallbackAction.RETRY
        assert decision.retry_after is not None
        assert decision.retry_after > NOW
        assert decision.escalation_payload is None

    def test_backoff_grows_with_attempt_number(self) -> None:
        coordinator = _coordinator()
        first = coordinator.decide(
            outcome=_needs_callback_outcome(),
            failure_reason=None,
            attempt_number=0,
            target_provider_name="Sunrise Dental",
            related_node_id=None,
            now=NOW,
        )
        second = coordinator.decide(
            outcome=_needs_callback_outcome(),
            failure_reason=None,
            attempt_number=1,
            target_provider_name="Sunrise Dental",
            related_node_id=None,
            now=NOW,
        )
        assert first.retry_after is not None
        assert second.retry_after is not None
        assert (second.retry_after - NOW) > (first.retry_after - NOW)

    def test_no_answer_case_is_modeled_as_outcome_none_with_failure_reason(self) -> None:
        coordinator = _coordinator()
        decision = coordinator.decide(
            outcome=None,
            failure_reason="call attempt failed: simulated Gemini outage",
            attempt_number=0,
            target_provider_name="Sunrise Dental",
            related_node_id=None,
            now=NOW,
        )
        assert decision.action is FallbackAction.RETRY
        assert "simulated Gemini outage" in decision.reasoning


class TestEscalationAfterExhaustion:
    def test_third_attempt_escalates_not_retries(self) -> None:
        coordinator = _coordinator()
        decision = coordinator.decide(
            outcome=_needs_callback_outcome(),
            failure_reason=None,
            attempt_number=2,
            target_provider_name="Sunrise Dental",
            related_node_id=NodeId("obligation-1"),
            now=NOW,
        )
        assert decision.action is FallbackAction.ESCALATE
        assert decision.retry_after is None
        payload = decision.escalation_payload
        assert isinstance(payload, FallbackEscalationPayload)
        assert payload.related_node_id == NodeId("obligation-1")
        assert payload.risk_tier is RiskTier.R2_APPROVE

    def test_escalation_never_returns_web_booking_fallback(self) -> None:
        coordinator = _coordinator()
        decision = coordinator.decide(
            outcome=_needs_callback_outcome(),
            failure_reason=None,
            attempt_number=5,
            target_provider_name="Sunrise Dental",
            related_node_id=None,
            now=NOW,
        )
        assert decision.action is not FallbackAction.WEB_BOOKING_FALLBACK
        assert decision.action is FallbackAction.ESCALATE
        assert "no web-booking fallback" in decision.reasoning.lower()

    def test_hostile_counterparty_outcome_can_still_go_through_the_full_ladder(self) -> None:
        hostile_outcome = CallOutcomeReport(
            call_id="call-2",
            target_provider_id=NodeId("provider-1"),
            transcript_source_document_id=NodeId("doc-2"),
            disclosure_given=True,
            claimed_slot=None,
            claimed_outcome_summary="Clinic declined to continue once told this was an automated caller.",
            out_of_bounds_encountered=False,
            requires_human_callback=True,
        )
        coordinator = _coordinator()
        decision = coordinator.decide(
            outcome=hostile_outcome,
            failure_reason=None,
            attempt_number=2,
            target_provider_name="Sunrise Dental",
            related_node_id=None,
            now=NOW,
        )
        assert decision.action is FallbackAction.ESCALATE


class TestCallerContractGuard:
    def test_calling_decide_for_a_clean_success_raises(self) -> None:
        clean_outcome = CallOutcomeReport(
            call_id="call-3",
            target_provider_id=NodeId("provider-1"),
            transcript_source_document_id=NodeId("doc-3"),
            disclosure_given=True,
            claimed_slot=NOW + timedelta(days=2),
            claimed_outcome_summary="Booked.",
            out_of_bounds_encountered=False,
            requires_human_callback=False,
        )
        coordinator = _coordinator()
        with pytest.raises(ValueError):
            coordinator.decide(
                outcome=clean_outcome,
                failure_reason=None,
                attempt_number=0,
                target_provider_name="Sunrise Dental",
                related_node_id=None,
                now=NOW,
            )

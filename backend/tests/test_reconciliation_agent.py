"""Tests for A28 Reconciliation Agent (`app.agents.ledger.reconciliation_agent`).

PHASES.md Gate 7's own acceptance list, this module's share of it:
- **A28 cannot move money — proven by test** (the single most important
  test in this file — `TestReadOnlyByConstruction`).
- Silent price hike detected from price history.
- Duplicate charges detected, legitimate re-billing not falsely flagged.
- SMS-vs-ledger mismatch -> `requires_dispute_branch=True`, never resolved
  by this module.

Unit tests only (fake Gemini, no network; a `FakeGraphReader` test double
in place of the Firestore emulator for the T0 read path).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from contracts.graph_types import LedgerEvent, LedgerEventKind, NodeId, RecurringCommitment
from contracts.tools import PermissionTier

from app.agents.ledger.errors import CurrencyMismatch
from app.agents.ledger.reconciliation_agent import AGENT_ID, ReconciliationAgent
from app.agents.ledger.types import ReconciliationRequest
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.solvers.salary_calculator import SalaryCalculationResult
from app.tools.errors import GatedToolRegistrationDenied, ToolTierNotPermitted
from tests.conftest import NOW, make_provenance

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_reader import FakeGraphReader
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router


class _DummyT3Tool:
    """A minimal `contracts.tools.Registrable` test double at T3 — used to
    prove A28's registry rejects a write tool even though T3 is not itself
    in `GATED_TIERS` (the allowed-tiers check, not the gated-tier-origin
    check, is what must catch this one). `Registrable` needs only `name`
    and `tier`, deliberately no `invoke` — this registration must fail
    before anything could ever call one."""

    def __init__(self) -> None:
        self.name = "graph_writer"
        self.tier = PermissionTier.T3_INTERNAL_WRITE


def _agent(
    *, texts: list[str] | None = None, series_by_commitment: dict[str, tuple[object, ...]] | None = None
) -> tuple[ReconciliationAgent, FakeGraphReader]:
    fake_models = FakeModels(texts=texts or ["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    reader = FakeGraphReader(series_by_commitment=series_by_commitment)
    return ReconciliationAgent(gemini_client=client, graph_reader=reader), reader


def _commitment(*, price_history: tuple[tuple[datetime, float], ...] = ()) -> RecurringCommitment:
    return RecurringCommitment(
        id=NodeId("commitment-society-maintenance"),
        provenance=make_provenance(),
        label="Sunrise Society maintenance",
        counterparty="Sunrise Apartments Society",
        amount=2500.0,
        cadence="monthly",
        price_history=price_history,
        last_used_at=NOW - timedelta(days=30),
        status="active",
    )


def _debit(
    node_id: str, *, amount: float, occurred_at: datetime, counterparty: str = "SUNRISE SOCIETY MAINT"
) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=LedgerEventKind.DEBIT,
        amount=amount,
        currency="INR",
        occurred_at=occurred_at,
        counterparty_raw=counterparty,
    )


class TestReadOnlyByConstruction:
    """Gate 7's literal item: "A28 cannot move money — proven by test"."""

    def test_registry_holds_only_a_t0_tool_at_construction(self) -> None:
        agent, _ = _agent()
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T0_READ
        assert agent.tool_registry.allowed_tiers == frozenset({PermissionTier.T0_READ})

    def test_registry_rejects_a_t3_write_tool(self) -> None:
        agent, _ = _agent()
        with pytest.raises(ToolTierNotPermitted) as exc_info:
            agent.tool_registry.register(_DummyT3Tool())
        assert exc_info.value.agent_id == str(AGENT_ID)
        assert not agent.tool_registry.has_tier(PermissionTier.T3_INTERNAL_WRITE)

    def test_registry_rejects_a_t6_payment_tool_even_from_a_mock_agent_side_location(self) -> None:
        agent, _ = _agent()
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)
        assert not agent.tool_registry.has_tier(PermissionTier.T6_FINANCIAL)
        assert len(agent.tool_registry.tools()) == 1  # still just the original T0 reader


class TestFetchSeries:
    def test_fetches_events_via_the_t0_tool(self) -> None:
        commitment = _commitment()
        event = _debit("ledger-1", amount=2500.0, occurred_at=NOW)
        agent, reader = _agent(series_by_commitment={str(commitment.id): (event,)})

        events = agent.fetch_series(commitment.id)

        assert events == (event,)
        assert reader.series_calls == [str(commitment.id)]


class TestPriceChangeDetection:
    def test_silent_price_hike_detected_from_price_history(self) -> None:
        commitment = _commitment(
            price_history=((NOW - timedelta(days=365), 2300.0), (NOW - timedelta(days=30), 2500.0))
        )
        agent, _ = _agent()

        result = agent.reconcile(ReconciliationRequest(commitment=commitment, series_events=()))

        price_findings = [f for f in result.findings if f.kind == "price_change"]
        assert len(price_findings) == 1
        finding = price_findings[0]
        assert finding.evidence["old_price"] == "2300.00"
        assert finding.evidence["new_price"] == "2500.00"
        assert finding.commitment_id == commitment.id
        assert finding.requires_dispute_branch is False
        assert result.model_tier == "deterministic"

    def test_no_finding_when_price_is_unchanged(self) -> None:
        commitment = _commitment(
            price_history=((NOW - timedelta(days=365), 2500.0), (NOW - timedelta(days=30), 2500.0))
        )
        agent, _ = _agent()

        result = agent.reconcile(ReconciliationRequest(commitment=commitment, series_events=()))

        assert [f for f in result.findings if f.kind == "price_change"] == []


class TestDuplicateDetection:
    def test_two_close_debits_flagged_as_duplicate(self) -> None:
        commitment = _commitment()
        e1 = _debit("ledger-1", amount=2500.0, occurred_at=NOW)
        e2 = _debit("ledger-2", amount=2500.0, occurred_at=NOW + timedelta(hours=2))
        agent, _ = _agent()

        result = agent.reconcile(ReconciliationRequest(commitment=commitment, series_events=(e1, e2)))

        duplicates = [f for f in result.findings if f.kind == "duplicate"]
        assert len(duplicates) == 1
        assert set(duplicates[0].subject_event_ids) == {e1.id, e2.id}

    def test_normal_monthly_gap_not_flagged_as_duplicate(self) -> None:
        commitment = _commitment()
        e1 = _debit("ledger-1", amount=2500.0, occurred_at=NOW - timedelta(days=30))
        e2 = _debit("ledger-2", amount=2500.0, occurred_at=NOW)
        agent, _ = _agent()

        result = agent.reconcile(ReconciliationRequest(commitment=commitment, series_events=(e1, e2)))

        assert [f for f in result.findings if f.kind == "duplicate"] == []


class TestMatchUnlinkedEvent:
    def test_matching_event_produces_recurrence_detected_finding(self) -> None:
        commitment = _commitment()
        unmatched = _debit("ledger-unmatched", amount=2500.0, occurred_at=NOW)
        response = json.dumps(
            {
                "matches": True,
                "looks_like_new_recurrence": False,
                "confidence": 0.92,
                "reasoning": "same merchant, same amount, same cadence",
            }
        )
        agent, _ = _agent(texts=[response])

        result = agent.reconcile(
            ReconciliationRequest(commitment=commitment, series_events=(), unmatched_events=(unmatched,))
        )

        recurrence_findings = [f for f in result.findings if f.kind == "recurrence_detected"]
        assert len(recurrence_findings) == 1
        assert recurrence_findings[0].commitment_id == commitment.id
        assert result.model_tier == "pro"
        assert result.prompt_version == "v1"

    def test_novel_recurrence_with_no_commitment_match(self) -> None:
        commitment = _commitment()
        unmatched = _debit("ledger-unmatched", amount=499.0, occurred_at=NOW, counterparty="NETFLIX")
        response = json.dumps(
            {
                "matches": False,
                "looks_like_new_recurrence": True,
                "confidence": 0.8,
                "reasoning": "looks like a new subscription, unrelated to this commitment",
            }
        )
        agent, _ = _agent(texts=[response])

        finding = agent.match_unlinked_event(event=unmatched, commitment=commitment)

        assert finding is not None
        assert finding.kind == "recurrence_detected"
        assert finding.commitment_id is None

    def test_no_match_and_no_recurrence_signal_produces_nothing(self) -> None:
        commitment = _commitment()
        unmatched = _debit("ledger-unmatched", amount=50.0, occurred_at=NOW, counterparty="LOCAL CAFE")
        response = json.dumps(
            {
                "matches": False,
                "looks_like_new_recurrence": False,
                "confidence": 0.7,
                "reasoning": "an unrelated one-off purchase",
            }
        )
        agent, _ = _agent(texts=[response])

        finding = agent.match_unlinked_event(event=unmatched, commitment=commitment)

        assert finding is None


class TestSmsLedgerMismatch:
    def test_mismatch_routes_to_dispute_branch(self) -> None:
        sms_event = _debit("sms-1", amount=2600.0, occurred_at=NOW)
        ledger_event = _debit("ledger-1", amount=2500.0, occurred_at=NOW)
        agent, _ = _agent()

        finding = agent.check_sms_ledger_mismatch(sms_event=sms_event, ledger_event=ledger_event)

        assert finding is not None
        assert finding.kind == "sms_ledger_mismatch"
        assert finding.requires_dispute_branch is True
        assert set(finding.subject_event_ids) == {sms_event.id, ledger_event.id}

    def test_matching_figures_produce_no_finding(self) -> None:
        sms_event = _debit("sms-1", amount=2500.0, occurred_at=NOW)
        ledger_event = _debit("ledger-1", amount=2500.5, occurred_at=NOW)
        agent, _ = _agent()

        finding = agent.check_sms_ledger_mismatch(sms_event=sms_event, ledger_event=ledger_event)

        assert finding is None

    def test_currency_mismatch_raises(self) -> None:
        sms_event = LedgerEvent(
            id=NodeId("sms-1"),
            provenance=make_provenance(),
            kind=LedgerEventKind.DEBIT,
            amount=100.0,
            currency="USD",
            occurred_at=NOW,
            counterparty_raw="X",
        )
        ledger_event = _debit("ledger-1", amount=100.0, occurred_at=NOW)
        agent, _ = _agent()

        with pytest.raises(CurrencyMismatch):
            agent.check_sms_ledger_mismatch(sms_event=sms_event, ledger_event=ledger_event)


class TestSalaryCrossCheck:
    def _salary_event(self, amount: float) -> LedgerEvent:
        return LedgerEvent(
            id=NodeId("ledger-maya-salary"),
            provenance=make_provenance(),
            kind=LedgerEventKind.SALARY,
            amount=amount,
            currency="INR",
            occurred_at=NOW,
            counterparty_raw="MAYA BAI",
        )

    def test_matching_payment_is_reconciled(self) -> None:
        agent, _ = _agent()
        recorded = self._salary_event(9000.0)

        finding = agent.check_salary_payment(
            recorded_event=recorded, computed_net_salary_due=9000.0, computed_currency="INR"
        )

        assert finding.kind == "salary_reconciled"
        assert finding.requires_dispute_branch is False

    def test_mismatched_payment_routes_to_dispute_branch(self) -> None:
        agent, _ = _agent()
        recorded = self._salary_event(9000.0)

        finding = agent.check_salary_payment(
            recorded_event=recorded, computed_net_salary_due=8500.0, computed_currency="INR"
        )

        assert finding.kind == "salary_mismatch"
        assert finding.requires_dispute_branch is True

    def test_non_salary_event_rejected(self) -> None:
        agent, _ = _agent()
        recorded = _debit("ledger-1", amount=9000.0, occurred_at=NOW)

        with pytest.raises(ValueError, match="SALARY"):
            agent.check_salary_payment(
                recorded_event=recorded, computed_net_salary_due=9000.0, computed_currency="INR"
            )

    def test_reconcile_folds_in_salary_cross_check(self) -> None:
        commitment = _commitment()
        agent, _ = _agent()
        recorded = self._salary_event(8500.0)
        computed = SalaryCalculationResult(
            staff_person_id=NodeId("person-maya"),
            month="2026-08",
            currency="INR",
            days_worked=22,
            days_absent=2,
            days_on_leave_unpaid=1,
            daily_rate=500.0,
            gross_amount=11000.0,
            total_advances_deducted=2000.0,
            advance_event_ids=(),
            net_salary_due=9000.0,
            floored_at_zero=False,
        )

        result = agent.reconcile(
            ReconciliationRequest(
                commitment=commitment,
                series_events=(),
                recorded_salary_event=recorded,
                computed_salary=computed,
            )
        )

        salary_findings = [f for f in result.findings if f.kind == "salary_mismatch"]
        assert len(salary_findings) == 1
        assert salary_findings[0].requires_dispute_branch is True

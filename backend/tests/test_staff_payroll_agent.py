"""Tests for A34 Staff Payroll Agent (`app.agents.ledger.staff_payroll_agent`).

PHASES.md Gate 7's own acceptance list, this module's share of it:
- Handwritten register -> correct salary (the clean path, no Gemini call).
- Low confidence -> shows image (both the whole-record-below-floor path
  and the specific-ambiguous-mark path).

Unit tests only (fake Gemini, no network; `FakeGraphWriter` +
`InMemoryIdempotencyStore` test doubles in place of the Firestore
emulator for the T3 write path).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AgentId,
    AttendanceRecord,
    Derivation,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Obligation,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)
from contracts.tools import PermissionTier

from app.agents.ledger.staff_payroll_agent import AGENT_ID, StaffPayrollAgent
from app.agents.ledger.types import PayrollRequest
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.solvers.salary_calculator import SalaryCalculationResult, calculate_salary
from app.tools.errors import GatedToolRegistrationDenied
from tests.conftest import make_language_profile

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
_DAILY_RATE = 500.0
_DUE_BY = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)


def _maya() -> Person:
    return Person(
        id=NodeId("person-maya"),
        provenance=_provenance(confidence=0.85),
        display_name="Maya",
        aliases=("Maya Bai",),
        role=PersonRole.STAFF,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=make_language_profile(),
    )


def _provenance(*, confidence: float, derivation: Derivation = Derivation.EXTRACTED) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=SourceRef(source_document_id=NodeId("doc-attendance-register"), region="whole-document"),
        confidence=confidence,
        deriving_agent=AgentId("A3"),
        created_at=_NOW,
    )


def _attendance(
    *,
    confidence: float = 0.9,
    derivation: Derivation = Derivation.EXTRACTED,
    daily_marks: dict[str, str] | None = None,
    days_present: int = 22,
    days_absent: int = 2,
    days_on_leave: int = 1,
) -> AttendanceRecord:
    return AttendanceRecord(
        id=NodeId("attendance-maya-2026-08"),
        provenance=_provenance(confidence=confidence, derivation=derivation),
        staff_person_id=NodeId("person-maya"),
        month="2026-08",
        days_present=days_present,
        days_absent=days_absent,
        days_on_leave=days_on_leave,
        total_days_in_period=25,
        daily_marks=daily_marks if daily_marks is not None else {"01": "present", "02": "absent"},
        advance_notations=("₹2,000 advance noted in margin, 12 Aug",),
    )


def _advance_event(amount: float = 2000.0) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId("ledger-maya-advance"),
        provenance=_provenance(confidence=0.8),
        kind=LedgerEventKind.ADVANCE,
        amount=amount,
        currency="INR",
        occurred_at=_NOW,
        counterparty_raw="MAYA BAI",
    )


def _agent(*, texts: list[str] | None = None) -> tuple[StaffPayrollAgent, FakeGraphWriter]:
    fake_models = FakeModels(texts=texts or ["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    writer = FakeGraphWriter()
    agent = StaffPayrollAgent(
        gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
    )
    return agent, writer


class TestPayCannotBeMovedByThisAgent:
    """Gate 7's structural analogue for A34: the write tool is T3
    (internal bookkeeping), never T6 (payment) — proven the same way
    A28's read-only claim is proven."""

    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _ = _agent()
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE
        assert agent.tool_registry.allowed_tiers == frozenset({PermissionTier.T3_INTERNAL_WRITE})

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
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


class TestCleanPathCorrectSalary:
    def test_clean_register_produces_correct_salary_with_no_model_call(self) -> None:
        attendance = _attendance(daily_marks={"01": "present", "02": "present", "03": "absent"})
        fake_models = FakeModels(texts=["{}"])
        client = GeminiClient(router=fake_router(fake_models))
        writer = FakeGraphWriter()
        agent = StaffPayrollAgent(
            gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
        )
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(_advance_event(),),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        expected = calculate_salary(
            attendance, daily_rate=_DAILY_RATE, advance_events=(_advance_event(),), currency="INR"
        )
        assert isinstance(result.salary, SalaryCalculationResult)
        assert result.salary.net_salary_due == expected.net_salary_due == 9000.0
        assert result.needs_human_review is False
        assert result.unresolved_marks == ()
        assert result.model_tier == "deterministic"
        assert len(fake_models.calls) == 0, "clean path must make no Gemini call at all"

    def test_obligation_written_with_expected_title(self) -> None:
        agent, writer = _agent()
        attendance = _attendance()
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(_advance_event(),),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.obligation_node_id is not None
        written = writer.nodes[result.obligation_node_id]
        assert isinstance(written, Obligation)
        assert written.title == "Pay Maya's salary"
        assert written.due_at == _DUE_BY
        assert written.obligation_type == "payment"


class TestBelowFloorNoSpecificDayShowsImage:
    def test_low_confidence_whole_record_needs_review_no_salary_guessed(self) -> None:
        agent, writer = _agent()
        attendance = _attendance(confidence=0.4, daily_marks={"01": "present"})
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.needs_human_review is True
        assert result.salary is None
        assert result.obligation_node_id is None
        assert result.register_image_ref == "doc-attendance-register"
        assert "confidence" in (result.review_reason or "")
        assert writer.write_node_calls == 0

    def test_ambiguous_derivation_also_forces_review(self) -> None:
        agent, _ = _agent()
        attendance = _attendance(
            confidence=0.9, derivation=Derivation.AMBIGUOUS, daily_marks={"01": "present"}
        )
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.needs_human_review is True
        assert result.salary is None


class TestSpecificAmbiguousMarks:
    def test_confidently_resolved_mark_produces_correct_salary(self) -> None:
        attendance = _attendance(
            daily_marks={"01": "present", "08": "unknown"},
            days_present=21,
            days_absent=2,
            days_on_leave=1,
        )
        response = json.dumps(
            {
                "resolutions": [
                    {
                        "day": "08",
                        "resolved_status": "present",
                        "confidence": 0.9,
                        "reasoning": "flanked by present marks on either side, consistent handwriting",
                    }
                ]
            }
        )
        agent, writer = _agent(texts=[response])
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(_advance_event(),),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.needs_human_review is False
        assert result.unresolved_marks == ()
        assert isinstance(result.salary, SalaryCalculationResult)
        # 21 original + 1 resolved "present" day = 22 days worked
        assert result.salary.days_worked == 22
        assert result.salary.net_salary_due == 9000.0
        assert result.model_tier == "pro"
        assert result.obligation_node_id is not None
        assert writer.write_node_calls == 1

    def test_unresolved_mark_blocks_salary_and_shows_image(self) -> None:
        attendance = _attendance(
            daily_marks={"01": "present", "08": "unknown"},
            days_present=21,
            days_absent=2,
            days_on_leave=1,
        )
        response = json.dumps(
            {
                "resolutions": [
                    {
                        "day": "08",
                        "resolved_status": "unresolved",
                        "confidence": 0.3,
                        "reasoning": "handwriting is illegible on this line, no adjacent pattern to lean on",
                    }
                ]
            }
        )
        agent, writer = _agent(texts=[response])
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.needs_human_review is True
        assert result.salary is None
        assert result.obligation_node_id is None
        assert len(result.unresolved_marks) == 1
        assert result.unresolved_marks[0].day == "08"
        assert result.register_image_ref == "doc-attendance-register"
        assert writer.write_node_calls == 0

    def test_low_confidence_resolution_is_treated_as_unresolved(self) -> None:
        """Even a `resolved_status` other than "unresolved" must not be
        trusted below `_MARK_RESOLUTION_CONFIDENCE_FLOOR` — never silently
        guessed."""
        attendance = _attendance(
            daily_marks={"01": "present", "08": "unknown"},
            days_present=21,
            days_absent=2,
            days_on_leave=1,
        )
        response = json.dumps(
            {
                "resolutions": [
                    {
                        "day": "08",
                        "resolved_status": "present",
                        "confidence": 0.4,
                        "reasoning": "weak guess only",
                    }
                ]
            }
        )
        agent, _ = _agent(texts=[response])
        request = PayrollRequest(
            staff_person=_maya(),
            attendance=attendance,
            advance_events=(),
            daily_rate=_DAILY_RATE,
            salary_due_by=_DUE_BY,
        )

        result = agent.process(request)

        assert result.needs_human_review is True
        assert result.salary is None


def test_agent_id_is_a34() -> None:
    assert str(AGENT_ID) == "A34"

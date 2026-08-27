"""A34 — Staff Payroll Agent (spec §10.3B, §15.7).

*Responsibility:* attendance -> days worked -> minus advances -> salary
due. Reads a real `AttendanceRecord` (per staff `Person`, per month) plus
real `LedgerEvent(kind=ADVANCE)` nodes for that person/period, and calls
`app.solvers.salary_calculator.calculate_salary` for the arithmetic —
**this module never re-derives that figure itself.**

*Model tier:* Pro-tier, but only for the specific interpretation work spec
names — resolving ambiguous/low-confidence marks in the underlying
register. A3 (Phase 3) already tags a below-floor handwritten mark
`Derivation.AMBIGUOUS`; `AttendanceRecord.daily_marks` carries the
per-day value `"unknown"` for exactly this case (contracts §5.4.2's
strictest-confidence-floor document type). This agent's job on those days
is to decide whether it can *confidently* resolve them from surrounding
context (adjacent days' patterns, the register's own remarks), or must
surface the original register image to a human — **never silently guess a
presence/absence mark.**

## The three paths (all three are real, all three are tested)

1. **Clean record** — no `"unknown"` marks, whole-record confidence clears
   `PayrollRequest.confidence_floor`. No Gemini call at all
   (`model_tier="deterministic"`); `calculate_salary` runs directly against
   the recorded rollup.
2. **Below-floor record, nothing specific to interpret** — no `"unknown"`
   marks, but the whole record's confidence is below floor (or its
   `Derivation` is `AMBIGUOUS`). No Gemini call — there is no specific day
   to ask about, only a general "this whole extraction wasn't confident."
   `needs_human_review=True`, `salary=None`, the register image is
   surfaced.
3. **Specific ambiguous marks** — one or more `"unknown"` days. A Pro-tier
   pass attempts to resolve each from context. Every unknown day resolved
   with `resolved_status != "unresolved"` and confidence clearing
   `_MARK_RESOLUTION_CONFIDENCE_FLOOR` gets folded into an *adjusted*
   `AttendanceRecord` (rollup counts incremented, `daily_marks` updated —
   still purely deterministic bookkeeping, done by this module in plain
   code, never by the model) before `calculate_salary` runs on it. **Any
   single day that cannot be confidently resolved blocks salary
   computation entirely** — this module never computes a salary while
   silently treating an unresolved day as absent (or present); that would
   itself be an unstated guess.

*Forbidden:* **paying.** This agent's only tool is a T3 graph-write tool
(`app.tools.graph_write_tool.GraphWriteTool`, `PermissionTier.T3_
INTERNAL_WRITE`) — the "Pay {name}'s salary" `Obligation` it writes is
real internal bookkeeping (spec's own framing: generating the obligation
is not the same as moving money), never a payment. This module has no
import path to any T6 tool, and its `ToolRegistry` is constructed with
`allowed_tiers=frozenset({PermissionTier.T3_INTERNAL_WRITE})` only —
attempting to register a T6 tool onto it fails exactly like A28's T0-only
registry does (see `backend/tests/test_staff_payroll_agent.py`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast

import structlog
from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    AttendanceRecord,
    Derivation,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Provenance,
)
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.salary_calculator import calculate_salary
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .json_utils import parse_json_response, require_float, require_list, require_str
from .types import PayrollRequest, PayrollResult, UnresolvedMark

AGENT_ID = AgentId("A34")

logger = structlog.get_logger(__name__)

_MARK_RESOLUTION_CONFIDENCE_FLOOR = 0.75
"""Below this, an individual day's model-proposed resolution is not
trusted — the day stays `"unknown"`, blocking salary computation and
forcing human review, exactly the same floor logic
`constraint_checker._HARD_CONSTRAINT_CONFIDENCE_FLOOR` establishes for its
own safety-critical case."""

_SALARY_PAYMENT_EFFORT_MINUTES = 5
"""Matches the seeded "Pay Maya's August salary" obligation's own
`effort_estimate_minutes` (`backend/seeds/demo_household.py`) — signing
off/initiating a salary payment is a brief, bounded task."""

_VALID_RESOLVED_STATUSES: frozenset[str] = frozenset({"present", "absent", "leave", "unresolved"})


@dataclass(frozen=True, slots=True)
class _MarkResolution:
    status: Literal["present", "absent", "leave", "unresolved"]
    confidence: float
    reasoning: str


def _marks_table(daily_marks: dict[str, str]) -> str:
    if not daily_marks:
        return "(no per-day marks recorded)"
    return "\n".join(
        f"- day {day}: {mark}" for day, mark in sorted(daily_marks.items(), key=lambda kv: int(kv[0]))
    )


def _register_image_ref(attendance: AttendanceRecord) -> str | None:
    source_ref = attendance.provenance.source_ref
    if source_ref is None:
        return None
    return str(source_ref.source_document_id)


class StaffPayrollAgent:
    """A34 Staff Payroll. Dependency-injected on a `GeminiClient` plus a
    `GraphWriter`/`IdempotencyStore` pair, wrapped immediately into a
    T3-only `ToolRegistry` and never stored directly on `self` (mirrors
    `ReconciliationAgent`'s T0-only construction exactly, one tier up)."""

    def __init__(
        self, *, gemini_client: GeminiClient, graph_writer: GraphWriter, idempotency_store: IdempotencyStore
    ) -> None:
        self._gemini_client = gemini_client
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T3_INTERNAL_WRITE})
        )
        self._tool_registry.register(
            GraphWriteTool(graph_writer=graph_writer, idempotency_store=idempotency_store)
        )

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same adversarial-proof reason
        `ReconciliationAgent.tool_registry` is — a T6 (or T4/T5) tool
        registration attempt against this registry must be rejected,
        checkable directly without running the agent."""
        return self._tool_registry

    def process(self, request: PayrollRequest) -> PayrollResult:
        """Runs one staff member's payroll for one month.

        Args:
            request: the real attendance record, real advance events, and
                this household's configured pay terms.

        Returns:
            A `PayrollResult` — see this module's docstring for the three
            paths this can take.

        Raises:
            errors.ModelResponseMalformed: an interpretation pass's model
                response could not be parsed as the expected JSON shape.
            contracts.errors.ToolFailure: the salary obligation write
                failed.
        """
        attendance = request.attendance
        register_ref = _register_image_ref(attendance)
        unknown_days = sorted(
            (day for day, mark in attendance.daily_marks.items() if mark == "unknown"),
            key=int,
        )
        record_below_floor = (
            attendance.provenance.confidence < request.confidence_floor
            or attendance.provenance.derivation is Derivation.AMBIGUOUS
        )

        if not unknown_days and not record_below_floor:
            return self._clean_path(request=request, register_ref=register_ref)

        if not unknown_days and record_below_floor:
            return self._below_floor_no_specific_day(request=request, register_ref=register_ref)

        return self._interpret_and_resolve(
            request=request, unknown_days=unknown_days, register_ref=register_ref
        )

    # -- path 1: clean -------------------------------------------------------

    def _clean_path(self, *, request: PayrollRequest, register_ref: str | None) -> PayrollResult:
        attendance = request.attendance
        salary = calculate_salary(
            attendance,
            daily_rate=request.daily_rate,
            advance_events=request.advance_events,
            currency=request.currency,
        )
        obligation_id = self._write_salary_obligation(
            request=request, attendance=attendance, salary_confidence=attendance.provenance.confidence
        )
        logger.info(
            "agents.ledger.a34.clean_path",
            staff_person_id=str(attendance.staff_person_id),
            month=attendance.month,
        )
        return PayrollResult(
            staff_person_id=attendance.staff_person_id,
            month=attendance.month,
            salary=salary,
            needs_human_review=False,
            unresolved_marks=(),
            review_reason=None,
            register_image_ref=register_ref,
            obligation_node_id=obligation_id,
            confidence=attendance.provenance.confidence,
            reasoning=(
                "attendance record confidence clears the floor with no ambiguous marks — "
                "salary computed directly from the recorded rollup, no interpretation needed."
            ),
            model_tier="deterministic",
        )

    # -- path 2: below floor, nothing specific to interpret -------------------

    def _below_floor_no_specific_day(
        self, *, request: PayrollRequest, register_ref: str | None
    ) -> PayrollResult:
        attendance = request.attendance
        reason = (
            f"attendance record confidence {attendance.provenance.confidence:.2f} is below the "
            f"{request.confidence_floor:.2f} floor (derivation={attendance.provenance.derivation.value}), "
            "with no single ambiguous day to interpret — the whole extraction was not confident enough "
            "to trust; the register image must be reviewed by a human before any salary is computed."
        )
        logger.info(
            "agents.ledger.a34.below_floor_no_specific_day",
            staff_person_id=str(attendance.staff_person_id),
            month=attendance.month,
            confidence=attendance.provenance.confidence,
        )
        return PayrollResult(
            staff_person_id=attendance.staff_person_id,
            month=attendance.month,
            salary=None,
            needs_human_review=True,
            unresolved_marks=(),
            review_reason=reason,
            register_image_ref=register_ref,
            obligation_node_id=None,
            confidence=attendance.provenance.confidence,
            reasoning=reason,
            model_tier="deterministic",
        )

    # -- path 3: specific ambiguous marks -------------------------------------

    def _interpret_and_resolve(
        self, *, request: PayrollRequest, unknown_days: list[str], register_ref: str | None
    ) -> PayrollResult:
        attendance = request.attendance
        resolutions = self._interpret_marks(
            staff_display_name=request.staff_person.display_name,
            attendance=attendance,
            unknown_days=unknown_days,
        )

        resolved: dict[str, Literal["present", "absent", "leave"]] = {}
        unresolved: list[UnresolvedMark] = []
        for day in unknown_days:
            resolution = resolutions.get(day)
            if (
                resolution is None
                or resolution.status == "unresolved"
                or resolution.confidence < _MARK_RESOLUTION_CONFIDENCE_FLOOR
            ):
                reason = (
                    resolution.reasoning
                    if resolution is not None
                    else "model returned no resolution for this day"
                )
                unresolved.append(UnresolvedMark(day=day, reason=reason))
            else:
                resolved[day] = resolution.status

        if unresolved:
            reason = (
                "the following day(s) could not be confidently interpreted even after review: "
                + ", ".join(mark.day for mark in unresolved)
                + " — register image must be shown to a human; no salary computed."
            )
            worst_confidence = min(
                (resolutions[day].confidence for day in unknown_days if day in resolutions), default=0.0
            )
            logger.info(
                "agents.ledger.a34.unresolved_marks",
                staff_person_id=str(attendance.staff_person_id),
                month=attendance.month,
                unresolved_days=[mark.day for mark in unresolved],
            )
            return PayrollResult(
                staff_person_id=attendance.staff_person_id,
                month=attendance.month,
                salary=None,
                needs_human_review=True,
                unresolved_marks=tuple(unresolved),
                review_reason=reason,
                register_image_ref=register_ref,
                obligation_node_id=None,
                confidence=worst_confidence,
                reasoning=reason,
                model_tier="pro",
            )

        adjusted_attendance = _apply_resolved_marks(attendance, resolved)
        salary = calculate_salary(
            adjusted_attendance,
            daily_rate=request.daily_rate,
            advance_events=request.advance_events,
            currency=request.currency,
        )
        overall_confidence = min(resolutions[day].confidence for day in unknown_days)
        reasoning = "resolved ambiguous mark(s) from context: " + "; ".join(
            f"day {day} -> {status}" for day, status in resolved.items()
        )
        obligation_id = self._write_salary_obligation(
            request=request, attendance=adjusted_attendance, salary_confidence=overall_confidence
        )
        logger.info(
            "agents.ledger.a34.resolved_marks",
            staff_person_id=str(attendance.staff_person_id),
            month=attendance.month,
            resolved_days=list(resolved),
        )
        return PayrollResult(
            staff_person_id=attendance.staff_person_id,
            month=attendance.month,
            salary=salary,
            needs_human_review=False,
            unresolved_marks=(),
            review_reason=None,
            register_image_ref=register_ref,
            obligation_node_id=obligation_id,
            confidence=overall_confidence,
            reasoning=reasoning,
            model_tier="pro",
        )

    def _interpret_marks(
        self, *, staff_display_name: str, attendance: AttendanceRecord, unknown_days: list[str]
    ) -> dict[str, _MarkResolution]:
        """Pro-tier: asks the model to resolve each `"unknown"`-marked day
        from the surrounding register context. Days the model does not
        mention at all are absent from the returned dict (treated as
        unresolved by the caller — never defaulted to any status here).

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape.
        """
        prompt = load_prompt("A34")
        rendered = prompt.text.format(
            staff_name=staff_display_name,
            month=attendance.month,
            marks_table=_marks_table(attendance.daily_marks),
            unknown_days=", ".join(unknown_days),
            advance_notations=("; ".join(attendance.advance_notations) or "(none noted)"),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_items = require_list(parsed, "resolutions", agent_id=AGENT_ID)

        resolutions: dict[str, _MarkResolution] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            day = require_str(item, "day", agent_id=AGENT_ID)
            status = require_str(item, "resolved_status", agent_id=AGENT_ID)
            if status not in _VALID_RESOLVED_STATUSES:
                status = "unresolved"
            confidence = require_float(item, "confidence", agent_id=AGENT_ID, default=0.0)
            reasoning = require_str(item, "reasoning", agent_id=AGENT_ID)
            resolutions[day] = _MarkResolution(
                status=cast('Literal["present", "absent", "leave", "unresolved"]', status),
                confidence=confidence,
                reasoning=reasoning,
            )
        return resolutions

    def _write_salary_obligation(
        self, *, request: PayrollRequest, attendance: AttendanceRecord, salary_confidence: float
    ) -> NodeId:
        source_ref = attendance.provenance.source_ref
        if source_ref is None:
            raise ValueError(
                "AttendanceRecord.provenance.source_ref must be populated to write a salary "
                "obligation — a single staff attendance register always has one real source document"
            )
        obligation = Obligation(
            id=NodeId(f"obligation:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.INFERRED,
                source_ref=source_ref,
                confidence=salary_confidence,
                deriving_agent=AGENT_ID,
                created_at=datetime.now(UTC),
            ),
            title=f"Pay {request.staff_person.display_name}'s salary",
            obligation_type="payment",
            due_at=request.salary_due_by,
            must_start_by=None,
            effort_estimate_minutes=_SALARY_PAYMENT_EFFORT_MINUTES,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.IMPLIED,
        )
        idempotency_key = IdempotencyKey(
            entity_id=str(attendance.staff_person_id), action_type="pay_salary", cycle=attendance.month
        ).as_str()

        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present
        result = tool.invoke_idempotent(idempotency_key, operation="write_node", node=obligation)
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=result.error or "salary obligation write failed",
                retryable=True,
            )
        return NodeId(str(result.value))


def _apply_resolved_marks(
    attendance: AttendanceRecord, resolved: dict[str, Literal["present", "absent", "leave"]]
) -> AttendanceRecord:
    """Pure, deterministic bookkeeping: folds confidently-resolved
    `"unknown"` days into a new `AttendanceRecord` — updates `daily_marks`
    for exactly those days and increments the matching rollup counter for
    each. Never touches a day that was not in `resolved`."""
    updated_marks = dict(attendance.daily_marks)
    added_present = added_absent = added_leave = 0
    for day, status in resolved.items():
        updated_marks[day] = status
        if status == "present":
            added_present += 1
        elif status == "absent":
            added_absent += 1
        elif status == "leave":
            added_leave += 1
    return replace(
        attendance,
        daily_marks=updated_marks,
        days_present=attendance.days_present + added_present,
        days_absent=attendance.days_absent + added_absent,
        days_on_leave=attendance.days_on_leave + added_leave,
    )


__all__ = ["AGENT_ID", "StaffPayrollAgent"]

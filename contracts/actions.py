"""GharOS — frozen action command contracts.

Owned exclusively by the CTO. Implements the Command pattern (PHASES.md
§2.2): every action that can touch the outside world is an object carrying
a risk tier, an idempotency key, and an audit reference, so the Approval
Gate can be enforced in *one* place (`backend/app/arbitration/`, owned by
E3 with E2 for confidence scoring) rather than scattered across call sites.

No Firestore, FastAPI, ADK, or other infrastructure import belongs here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

# ---------------------------------------------------------------------------
# Risk tiers (spec §18.1)
# ---------------------------------------------------------------------------


class RiskTier(str, Enum):
    """R0-R4. Determines autonomy vs. approval — spec §18.1 is the source
    of truth for the policy attached to each tier; this enum is the shape
    only."""

    R0_SILENT = "R0"
    """Reversible, internal, no external effect. Execute; log."""
    R1_NOTIFY = "R1"
    """Reversible, low-impact, visible. Execute; notify."""
    R2_APPROVE = "R2"
    """External communication, non-financial. Require approval."""
    R3_EXPLICIT_APPROVE = "R3"
    """Any movement of money. Require approval + evidence bundle."""
    R4_ESCALATE_ONLY = "R4"
    """Irreversible, high-stakes, emotionally loaded. Never auto-execute;
    present options only."""


_TIER_ORDER: dict[RiskTier, int] = {
    RiskTier.R0_SILENT: 0,
    RiskTier.R1_NOTIFY: 1,
    RiskTier.R2_APPROVE: 2,
    RiskTier.R3_EXPLICIT_APPROVE: 3,
    RiskTier.R4_ESCALATE_ONLY: 4,
}


def tier_at_least(tier: RiskTier, floor: RiskTier) -> bool:
    """True if `tier` is at or above `floor` in strictness. Used by the
    confidence arbiter to implement 'confidence below threshold downgrades
    an action at least one tier' and 'hard-constraint involvement forces at
    least R2' (spec §18.2) without string-comparing enum values."""
    return _TIER_ORDER[tier] >= _TIER_ORDER[floor]


def downgrade_tier(tier: RiskTier) -> RiskTier:
    """One step stricter. R4 has no further downgrade — it is already the
    ceiling."""
    order = _TIER_ORDER[tier]
    stricter = [t for t, o in _TIER_ORDER.items() if o == order + 1]
    return stricter[0] if stricter else tier


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Generated from (entity_id, action_type, cycle_or_period) per spec
    §19.1. Payments are the strictest case: one debit per due-ID per cycle,
    enforced at the tool level (contracts/tools.py), not the agent level."""

    entity_id: str
    action_type: str
    cycle: str

    def as_str(self) -> str:
        return f"{self.entity_id}:{self.action_type}:{self.cycle}"


# ---------------------------------------------------------------------------
# Approval evidence bundle (spec §18.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Every approval request carries these five things, no exceptions
    (spec §18.2). The Approval Gate UI (E4) renders this shape directly."""

    proposed_action: str
    reasoning: str
    evidence_consulted: tuple[str, ...]
    confidence: float
    consequence_if_wrong: str


# ---------------------------------------------------------------------------
# Action command object
# ---------------------------------------------------------------------------

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class ActionResult(Generic[ResultT]):
    """Result-type wrapper for an action outcome (PHASES.md §2.2: Result
    types for expected failure paths, exceptions for the unexpected).
    Exactly one of `value` / `error` is set."""

    ok: bool
    value: ResultT | None
    error: str | None

    @staticmethod
    def success(value: ResultT) -> ActionResult[ResultT]:
        return ActionResult(ok=True, value=value, error=None)

    @staticmethod
    def failure(error: str) -> ActionResult[ResultT]:
        return ActionResult(ok=False, value=None, error=error)


@dataclass(frozen=True, slots=True)
class AuditRef:
    """Pointer to the AuditRecord written for this action. An Action must
    hold a *populated* AuditRef before `execute()` runs — this is what
    makes 'audit before execute' (safety invariant #2) structural rather
    than a documentation promise. See `write_before_execute` in
    `backend/app/audit/` (E1)."""

    audit_record_id: str
    written_at: datetime


class Action(ABC, Generic[ResultT]):
    """Base contract every action object satisfies. Concrete actions live
    in `backend/app/tools/` (E3) or `backend/app/solvers/` (E1 for
    deterministic actions); this class defines the shape only.

    An `Action` never reasons — by the time one exists, arbitration has
    already decided it should run. Constructing an `Action` is not the same
    as approving it; `execute()` must itself refuse to run without a
    populated `audit_ref`, and for T4/T5/T6-tier actions, without a
    corresponding APPROVED ApprovalRequest (see `tools.py:PermissionTier`).
    """

    risk_tier: RiskTier
    idempotency_key: IdempotencyKey
    audit_ref: AuditRef | None

    @abstractmethod
    def execute(self) -> ActionResult[ResultT]:
        """Perform the effect. Must raise contracts.errors.ToolFailure (or
        return ActionResult.failure) on any failure — never fabricate a
        success (safety invariant #7)."""
        raise NotImplementedError

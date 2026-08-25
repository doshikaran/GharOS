"""Shared, non-agent-specific dataclasses for `backend/app/arbitration/`.

Mirrors the role `app.agents.consequence.types` plays for A12-A16: one
place every arbiter/approval-gate/escalation-agent module imports the same
request/result shapes from, so the pipeline (propose -> arbitrate ->
approve/escalate -> execute) stays legible end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import AgentId, NodeId, SourceRef

# ---------------------------------------------------------------------------
# A57 Confidence Arbiter — input/output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """One not-yet-existing action a Layer 3 reasoning agent wants to
    happen. This is the *only* shape a reasoning agent ever produces on
    the path to action — reasoning agents construct `ProposedAction`s
    freely (it carries no action credential, just data) but never a
    `contracts.actions.Action` itself.

    `action_type` must be one of `app.reasoning.risk_policy.ActionTypes` —
    `ConfidenceArbiter.evaluate` classifies it via
    `app.reasoning.risk_policy.classify_risk_tier`, which raises
    `app.reasoning.errors.ActionTypeNotClassified` for anything else
    (never silently resolves to a default tier — spec §19.2).
    """

    action_type: str
    entity_id: str
    """The entity this action's `contracts.actions.IdempotencyKey` is
    scoped to (e.g. a due's id, a mandate's id) — together with
    `action_type` and `cycle`, spec §19.1's three-part idempotency key."""
    cycle: str
    """The billing/scheduling cycle this action belongs to (e.g.
    `"2026-08"`) — spec §19.1: "one debit per due-ID per cycle"."""
    target_node_id: NodeId
    """The real graph node this action, once executed, `ACTS_ON`
    (spec ADR-012) — an OBLIGATION, LEDGER_EVENT, VENDOR, PROVIDER, or
    RECURRING_COMMITMENT."""
    confidence: float
    involves_hard_constraint: bool
    reasoning: str
    evidence_consulted: tuple[str, ...]
    consequence_if_wrong: str
    proposed_by: AgentId
    source_ref: SourceRef | None
    """Traces back to whatever originally implied this action (a
    SOURCE_DOCUMENT region, via the upstream OBLIGATION/LEDGER_EVENT's own
    provenance) — `None` only when genuinely no single source exists
    (e.g. a scheduled recurring due with no new triggering document),
    matching `contracts.graph_types.Provenance`'s own AMBIGUOUS-with-no-
    source-ref allowance."""


class ArbiterDecision(StrEnum):
    """spec §15.12 A57: "decide execute / approve / escalate / discard"."""

    EXECUTE = "execute"
    """R0/R1 — auto-execute (log for R0, notify for R1). Never gated."""
    APPROVE = "approve"
    """R2/R3 — routed to the Approval Gate; a human must approve before
    the underlying T4/T5/T6 tool ever runs."""
    ESCALATE = "escalate"
    """R4, or a below-floor action already at the R4 ceiling — routed to
    A58 Escalation Agent; never auto-executed, options only."""
    DISCARD = "discard"
    """Confidence too low to act on *or* present at all (spec §19.2:
    "downgrade tier, escalate, or discard — never silently proceed"). Not
    a silent failure — a DISCARD decision is itself the auditable
    outcome; see `ArbiterResult.discard_reason`."""


@dataclass(frozen=True, slots=True)
class ArbiterResult:
    """`ConfidenceArbiter.evaluate`'s complete output — everything a
    downstream caller (Approval Gate, Escalation Agent, or an R0/R1
    executor) needs, with no further graph reads required."""

    proposed_action: ProposedAction
    decision: ArbiterDecision
    final_risk_tier: RiskTier
    """The tier `decision` was computed from — may differ from
    `app.reasoning.risk_policy.classify_risk_tier(proposed_action.
    action_type)`'s base classification once the hard-constraint floor and
    any confidence-driven downgrade have been applied."""
    confidence: float
    evidence_bundle: EvidenceBundle
    escalated_to_pro: bool
    """`True` only when confidence sat within the borderline band of the
    tier's floor and a real Pro-tier call adjudicated it (cost discipline:
    never `True` for a clearly-above or clearly-below case)."""
    discard_reason: str | None = None
    """Populated only when `decision is ArbiterDecision.DISCARD`."""


# ---------------------------------------------------------------------------
# Approval Gate — output shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """What happened when `ApprovalGate.approve_and_execute` (or its
    expiry path) ran for one `ApprovalRequest`."""

    status: str
    """A `contracts.graph_types.ApprovalStatus` value, as `str` (mirrors
    `contracts.graph_types.ApprovalRequest.risk_tier`'s own str-typing to
    avoid a circular import)."""
    approval_request_id: NodeId
    action_record_id: NodeId | None
    """Set only when `status == "approved"` and the underlying tool
    invocation itself succeeded — `None` for EXPIRED, for a rejected
    request, and for an APPROVED request whose tool invocation failed
    (the audit record still exists; see `ApprovalGate`'s own docstring)."""
    tool_result: object | None
    """The underlying `contracts.actions.ActionResult` from the gated
    tool's invocation, or `None` when no invocation was attempted
    (EXPIRED / not-yet-approved paths). Typed `object` here (rather than
    importing `ActionResult` for a `Generic[T]` this dataclass has no
    concrete `T` for) — callers narrow it themselves."""


# ---------------------------------------------------------------------------
# A58 Escalation Agent — input/output shapes
# ---------------------------------------------------------------------------


class EscalationReason(StrEnum):
    """The three escalation triggers spec §15.12/PHASES.md Phase 5 name
    for A58: "Route escalations to the right member... (expired approval,
    R4 action, low-confidence discard)"."""

    APPROVAL_EXPIRED = "approval_expired"
    R4_ACTION = "r4_action"
    LOW_CONFIDENCE_DISCARD = "low_confidence_discard"


@dataclass(frozen=True, slots=True)
class EscalationContext:
    """What A58 needs to route one escalation. `involves_*` flags are the
    caller's (Approval Gate / Confidence Arbiter's) own judgment about
    what capability is relevant — A58 does not re-derive them from free
    text."""

    reason: EscalationReason
    action_type: str
    summary: str
    risk_tier: RiskTier | None
    involves_financial: bool
    involves_signature: bool
    involves_medical: bool
    evidence_bundle: EvidenceBundle | None
    related_node_id: NodeId | None


@dataclass(frozen=True, slots=True)
class EscalationRouting:
    """A58's output: who to notify, on what basis, with what briefing."""

    reason: EscalationReason
    candidate_person_ids: tuple[NodeId, ...]
    routing_basis: str
    """Human-readable justification for *why* these people — a capability
    field name, or the explicit DEBT-006 degradation note when no finer
    signal applies. Never blank."""
    briefing: str
    """"Enough context to decide" (spec §15.12) — Flash-composed when the
    live call succeeds, a deterministic template otherwise (see
    `escalation_agent.py`)."""
    briefing_is_template_fallback: bool


__all__ = [
    "ApprovalOutcome",
    "ArbiterDecision",
    "ArbiterResult",
    "EscalationContext",
    "EscalationReason",
    "EscalationRouting",
    "ProposedAction",
]

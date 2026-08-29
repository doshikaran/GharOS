"""Risk-tier classification and confidence-floor policy for GharOS actions.

PHASES.md Phase 5, "Work — E2": "Standardised confidence scoring; risk-tier
classification per action type." This module is the policy layer that
`backend/app/tools/` (E3's **A57 Confidence Arbiter** and **Approval
Gate**, built this same phase) imports for exactly two decisions:

  1. What `contracts.actions.RiskTier` a given action type maps to —
     `classify_risk_tier(action_type)`.
  2. What confidence floor applies at a given `RiskTier` —
     `confidence_floor(tier)`.

A third function, `apply_hard_constraint_floor`, exposes spec §18.2 rule 2
("hard-constraint involvement forces at least R2") as a standalone
composable rule the Arbiter applies on top of (1).

**This module builds the policy, not the Arbiter.** It holds no action
credential, imports nothing from `contracts.tools`, and calls no tool —
consistent with the E2 charter's structural rule that a reasoning-layer
module never gets an import path to an action-executing tool
(`.claude/agents/e2.md`: "reasoning agents never hold action
credentials... a reasoning agent must have no import path to
`contracts.tools.ApprovalGatedTool` or its subclasses"). It proposes a
classification; the Arbiter (E3) decides execute / approve / escalate /
discard and is the only path to action (spec §15 A57).

Spec sources — read both before changing this file:
  - GharOS_Build_Spec_v2.md §18 (Human-in-the-loop policy): §18.1's risk-
    tier table is the source of truth for R0-R4's definitions, policies,
    and worked examples; §18.2's five rules govern how tiers move.
  - GharOS_Build_Spec_v2.md §19.2 (Confidence): "Thresholds configurable
    per action tier — safety-critical paths (hard constraints, payments,
    medical, voice) strictest. Below threshold: downgrade tier, escalate,
    or discard. Never silently proceed."
"""

from __future__ import annotations

import structlog
from contracts.actions import RiskTier, tier_at_least

from .errors import ActionTypeNotClassified

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Action-type vocabulary
# ---------------------------------------------------------------------------


class ActionTypes:
    """Canonical action-type identifiers this policy module classifies.

    A plain namespace of `str` constants, not an `Enum` — action-type
    strings originate all over `backend/app/agents/` (61+ agents across
    every subsystem) and eventually land on `contracts.actions.Action`
    objects built by E1's solvers and E3's tools; forcing every caller to
    import and depend on an E2-owned `Enum` type would couple those
    modules to this one for no benefit over a shared string constant.
    Named constants (gharos-standards rule 3: "no magic values") keep call
    sites typo-safe without that coupling.

    Grouped by risk tier below. Each constant's docstring-adjacent comment
    in `_ACTION_TYPE_RISK_TIER` cites the spec §18.1 example or roster
    agent (spec §15 / `gharos-agent-roster` skill) that grounds it — no
    entry here is invented without a textual basis.
    """

    # --- R0 — Silent (execute; log) ----------------------------------
    GRAPH_WRITE = "graph_write"
    CALENDAR_ENTRY = "calendar_entry"
    INFORMATION_PREP = "information_prep"
    GRAPH_MAINTENANCE = "graph_maintenance"

    # --- R1 — Notify (execute; notify) -------------------------------
    DRAFT_MESSAGE = "draft_message"
    PROPOSE_MENU_SUBSTITUTION = "propose_menu_substitution"
    SHOPPING_LIST = "shopping_list"
    RENEGOTIATION_PROPOSAL = "renegotiation_proposal"
    ESCALATION_WITH_OPTIONS = "escalation_with_options"

    # --- R2 — Approve (external communication, non-financial) -------
    SEND_MESSAGE_EXTERNAL = "send_message_external"
    SUBMIT_FORM = "submit_form"
    PLACE_CALL = "place_call"
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    CONFIRM_CONSTRAINT_PROMOTION = "confirm_constraint_promotion"
    """Phase 14 (ADR-021 Decision 4) — see `_ACTION_TYPE_RISK_TIER`'s
    comment for the full R2 justification."""

    # --- R3 — Explicit approve (any movement of money) --------------
    PAY_DUES = "pay_dues"
    PAY_SALARY = "pay_salary"
    CANCEL_MANDATE = "cancel_mandate"
    FILE_DISPUTE = "file_dispute"

    # --- R4 — Escalate only (irreversible, high-stakes, emotional) --
    RELOCATION = "relocation"
    PROPERTY_PURCHASE = "property_purchase"
    CARE_ARRANGEMENT = "care_arrangement"
    END_STAFF_EMPLOYMENT = "end_staff_employment"
    MEDICAL_CHOICE = "medical_choice"


# ---------------------------------------------------------------------------
# The classification table
# ---------------------------------------------------------------------------
#
# Every entry is grounded either directly in a spec §18.1 worked example
# (R0-R4 columns each name concrete examples) or in a concrete effect a
# named roster agent (spec §15 / gharos-agent-roster skill) actually
# produces. Agents whose output never becomes a `contracts.actions.Action`
# — pure analysis/reasoning/ranking/framing agents such as A9, A17, A19's
# verification half, A28 (read-only by construction), A29, A35, A50-A52 —
# are deliberately absent: they have no action type to classify because
# they take no action. Their *downstream* actions, once one exists, are
# classified under the appropriate entry below (e.g. A29 Leakage
# Detection's "still wanted?" judgment has no action type of its own; the
# cancellation it may eventually trigger is `CANCEL_SUBSCRIPTION`).

_ACTION_TYPE_RISK_TIER: dict[str, RiskTier] = {
    # ----- R0 — Silent: reversible, internal, no external effect -------
    # spec §18.1 worked example, verbatim: "Graph write". Covers every
    # internal derived-node/edge write across the roster: A7 Graph
    # Builder, A15 Obligation Writer, A18 Valuation Extraction Agent
    # (writing the cost matrix), A27 Financial Signal Ingestion
    # (normalizing to LEDGER_EVENTs), A34 Staff Payroll Agent (writing
    # the computed salary-due figure — distinct from PAY_SALARY, which is
    # the money movement itself), A49 Council Recorder (COUNCIL_POSITION
    # writes), and A16 Constraint Learner (writing a CandidateConstraint
    # node pinned to status="pending_confirmation" — still only a graph
    # write; a hard constraint is never written without human
    # confirmation, per A16's forbidden list, so this never needs to be
    # anything stricter than R0).
    ActionTypes.GRAPH_WRITE: RiskTier.R0_SILENT,
    # spec §18.1 worked example, verbatim: "calendar entry". A25 Window
    # Scheduling committing a found window to the shared household
    # calendar.
    ActionTypes.CALENDAR_ENTRY: RiskTier.R0_SILENT,
    # spec §18.1 worked example, verbatim: "information prep". Read-only
    # retrieval with no effect on the world: A24 Unblocker/Preparation's
    # fetch stage, A36 Grounding/Research, A50 Requirement Clarifier's
    # graph query, A51 Service Discovery's provider search, A8 Graph
    # Query Agent's traversals.
    ActionTypes.INFORMATION_PREP: RiskTier.R0_SILENT,
    # A11 Graph Maintainer: scheduled supersession/staleness/orphan/
    # integrity work. Internal, reversible via versioning (immutability-
    # by-default per gharos-standards means "maintenance" supersedes, it
    # never destructively deletes — and A11 is explicitly forbidden from
    # ever pruning DECISION/OUTCOME/provenance/hard-constraint nodes), no
    # external effect. Kept distinct from GRAPH_WRITE because it is
    # system upkeep over existing claims rather than a new derived claim,
    # but lands at the same tier by the same reasoning.
    ActionTypes.GRAPH_MAINTENANCE: RiskTier.R0_SILENT,
    # ----- R1 — Notify: reversible, low-impact, visible ----------------
    # spec §18.1 worked example, verbatim: "Draft message". Covers A24
    # Unblocker/Preparation's pre-draft stage ("no send without
    # approval" is exactly the R1/R2 boundary this table draws), A30
    # Recovery Drafting (cancellations/disputes/claims/price-adjustment
    # drafts — "Tools: draft only. Forbidden: sending, moving money" is
    # this same boundary from A30's side), and A33 Vendor Relations'
    # draft-communication tool.
    ActionTypes.DRAFT_MESSAGE: RiskTier.R1_NOTIFY,
    # spec §18.1 worked example, verbatim: "propose menu substitution".
    ActionTypes.PROPOSE_MENU_SUBSTITUTION: RiskTier.R1_NOTIFY,
    # spec §18.1 worked example, verbatim: "shopping list".
    ActionTypes.SHOPPING_LIST: RiskTier.R1_NOTIFY,
    # A20 Renegotiation Trigger: "Monitor for life events warranting
    # re-allocation." The trigger surfaces a visible, reversible proposal
    # to the household that a re-allocation conversation may be
    # warranted — it does not itself reallocate anything, so it matches
    # R1's "reversible, low-impact, visible" definition exactly rather
    # than committing to anything.
    ActionTypes.RENEGOTIATION_PROPOSAL: RiskTier.R1_NOTIFY,
    # A26 Slippage Analyst: "after N attempts escalate with options
    # (drop / delegate / pay)." Presenting options for a human to choose
    # among is visible and reversible (no option is enacted merely by
    # being presented) — R1, not an approval-gated action in itself.
    ActionTypes.ESCALATION_WITH_OPTIONS: RiskTier.R1_NOTIFY,
    # ----- R2 — Approve: external communication, non-financial ---------
    # spec §18.1 worked example, verbatim: "Send message outside
    # household". Covers A31 Follow-up/Persistence's re-contact-on-cadence
    # (each re-contact is a fresh outbound message to an external vendor/
    # provider) and any A33 Vendor Relations communication once it moves
    # from draft to sent.
    ActionTypes.SEND_MESSAGE_EXTERNAL: RiskTier.R2_APPROVE,
    # spec §18.1 worked example, verbatim: "submit form". A56 Fallback
    # Coordinator's web-booking fallback path.
    ActionTypes.SUBMIT_FORM: RiskTier.R2_APPROVE,
    # spec §18.1 worked example, bolded in the source table: "**place a
    # call**". A53 Call Planner sets the bounds; A54 Voice Call Agent
    # executes within them (voice call tools are themselves
    # approval-gated per A54's roster entry, consistent with this tier).
    ActionTypes.PLACE_CALL: RiskTier.R2_APPROVE,
    # Vendor-facing service cancellation (e.g. "cancel the gym
    # membership") — the downstream action A29 Leakage Detection's
    # "still worth it?" judgment may eventually trigger, submitted to the
    # vendor as a request/form. JUDGMENT CALL, documented per the task's
    # instruction to flag ambiguity explicitly: this is easy to conflate
    # with CANCEL_MANDATE (R3) below because both use the word "cancel."
    # They are kept deliberately distinct, not collapsed: CANCEL_SUBSCRIPTION
    # is a request to a vendor to stop providing a service — no money
    # moves as a direct effect of the action itself, it is structurally
    # the same shape as SUBMIT_FORM/SEND_MESSAGE_EXTERNAL. CANCEL_MANDATE
    # is an instruction to a bank/payment rail (NACH/UPI Autopay mandate)
    # that directly touches the money-movement machinery, which is
    # exactly spec §18.1's own R3 worked example. If a future concrete
    # case is genuinely ambiguous between the two (e.g. cancelling a
    # subscription automatically also revokes its payment mandate in one
    # vendor flow), the stricter tier (R3, CANCEL_MANDATE) applies per
    # the spec's own "safety-critical paths strictest" principle — this
    # table does not encode that automatically because it is a
    # per-vendor-integration fact, not a general rule, but a future
    # caller must not default such a case to R2.
    ActionTypes.CANCEL_SUBSCRIPTION: RiskTier.R2_APPROVE,
    # Phase 14 (ADR-021 Decision 4) — Memory Consolidation service's
    # constraint-promotion pass (`app.reasoning.constraint_promotion`, not
    # a numbered agent — spec §15.9 lists Memory Consolidation under
    # "Services (not LLM agents)"). Confirming a repeated signal as a new
    # household-wide HARD constraint is not itself external communication,
    # but it is classified here at R2 for the same reason `apply_hard_
    # constraint_floor` already encodes structurally for every other
    # agent's hard-constraint-adjacent action: spec §18.2 rule 2, "hard-
    # constraint involvement forces at least R2." Every candidate this
    # pass produces is, by definition, a proposal to make something HARD.
    # R2, not R3 (no money moves) and not R4 (R4 never reaches
    # `ApprovalGate.request_approval` at all — it routes to escalation —
    # which would contradict "confirmation-gated via the existing
    # Approval Gate flow," ADR-021's explicit requirement).
    ActionTypes.CONFIRM_CONSTRAINT_PROMOTION: RiskTier.R2_APPROVE,
    # ----- R3 — Explicit approve: any movement of money -----------------
    # spec §18.1 worked example, verbatim: "Pay dues".
    ActionTypes.PAY_DUES: RiskTier.R3_EXPLICIT_APPROVE,
    # spec §18.1 worked example, verbatim: "pay salary". A34 Staff
    # Payroll Agent computes what is owed (GRAPH_WRITE, R0) but is itself
    # explicitly forbidden from paying — PAY_SALARY is the action type
    # the payment tool executes once a human approves A34's computation.
    ActionTypes.PAY_SALARY: RiskTier.R3_EXPLICIT_APPROVE,
    # spec §18.1 worked example, verbatim: "cancel mandate". See the
    # CANCEL_SUBSCRIPTION comment above for the deliberate distinction
    # from vendor-service cancellation.
    ActionTypes.CANCEL_MANDATE: RiskTier.R3_EXPLICIT_APPROVE,
    # spec §18.1 worked example, verbatim: "file dispute". A32 Dispute
    # Branch assembles both conflicting figures with evidence for human
    # resolution but is explicitly forbidden from choosing which is
    # correct — the formal filing action this produces concerns
    # contested money (can trigger holds, chargebacks, or a debit) and is
    # therefore R3, not merely R2, even though its immediate effect is a
    # communication rather than a debit — spec places it in the R3 row
    # explicitly, and "safety-critical paths strictest" backs treating a
    # financial dispute as money-adjacent rather than as a plain
    # non-financial external message.
    ActionTypes.FILE_DISPUTE: RiskTier.R3_EXPLICIT_APPROVE,
    # ----- R4 — Escalate only: irreversible, high-stakes, emotional -----
    # spec §18.1 worked examples, verbatim, one entry each: "Relocation,
    # property purchase, care arrangements, ending staff employment,
    # medical choices." The Household Council (A41-A49) may produce a
    # brief informing any of these but never resolves them itself (spec
    # §18.2: "The Council never resolves R4 — it produces a brief; humans
    # decide") — these action types exist in this table for whatever
    # downstream system component eventually needs to route the human's
    # decision, not for a Council agent to invoke directly.
    ActionTypes.RELOCATION: RiskTier.R4_ESCALATE_ONLY,
    ActionTypes.PROPERTY_PURCHASE: RiskTier.R4_ESCALATE_ONLY,
    ActionTypes.CARE_ARRANGEMENT: RiskTier.R4_ESCALATE_ONLY,
    ActionTypes.END_STAFF_EMPLOYMENT: RiskTier.R4_ESCALATE_ONLY,
    ActionTypes.MEDICAL_CHOICE: RiskTier.R4_ESCALATE_ONLY,
}


def classify_risk_tier(action_type: str) -> RiskTier:
    """Resolve a concrete action type to its `contracts.actions.RiskTier`.

    This is a *base* classification only — it does not yet account for
    confidence or hard-constraint involvement. Callers (the Confidence
    Arbiter, A57) compose this with `confidence_floor` and
    `apply_hard_constraint_floor` to reach a final tier for one proposed
    action, per spec §18.2's rules.

    Args:
        action_type: one of the `ActionTypes` constants (or any string —
            this function takes `str` so callers are not forced to import
            `ActionTypes` themselves, matching the shape the task asked
            for), e.g. `"pay_dues"`.

    Returns:
        The `RiskTier` this action type is classified at.

    Raises:
        ActionTypeNotClassified: `action_type` has no entry in the
            classification table. This is deliberate — an unmapped action
            type must never silently resolve to a permissive tier (spec
            §19.2: "never silently proceed"). Raising forces the caller
            to handle the gap explicitly, which in practice means routing
            to escalation (A58) rather than guessing, mirroring the
            precedent `contracts.errors.RegistryGap` sets for the
            Document-Type Registry.
    """
    tier = _ACTION_TYPE_RISK_TIER.get(action_type)
    if tier is None:
        logger.warning(
            "reasoning.risk_policy.action_type_not_classified",
            action_type=action_type,
        )
        raise ActionTypeNotClassified(action_type=action_type)
    return tier


# ---------------------------------------------------------------------------
# Confidence floors
# ---------------------------------------------------------------------------
#
# spec §19.2: "Thresholds configurable per action tier — safety-critical
# paths (hard constraints, payments, medical, voice) strictest." Design
# reasoning per tier, strictly increasing with strictness:
#
#   R0  0.50 — Silent, auto-executed, internal, reversible-by-supersession
#       (a graph write is versioned, never destructive — a wrong R0 write
#       can be corrected by a later write with better provenance). The
#       lowest bar in the system, but never zero or absent: every derived
#       node/edge/action carries a confidence score unconditionally (spec
#       §19.2 first sentence) and even a silent write must clear a basic
#       sanity floor rather than being accepted on pure noise.
#   R1  0.60 — Reversible and low-impact, but now visible to the
#       household (a draft, a proposed substitution, a shopping-list
#       entry) — one notch stricter than R0 because a wrong R1 output is
#       not just logged, a person sees it.
#   R2  0.75 — The action now leaves the household: an external party
#       receives a message, a form, or a phone call. Wrong here costs
#       real-world trust with a vendor/institution and cannot be
#       silently corrected the way an internal write can — a
#       meaningfully higher bar than R1.
#   R3  0.88 — Any movement of money. Spec §19.2 names "payments" as one
#       of the four explicitly-cited safety-critical paths, and spec
#       §18.1 requires an explicit approval *plus evidence bundle* for
#       this tier — the floor here reflects that this is not merely
#       "needs a human," it needs a human backed by a well-grounded
#       proposal.
#   R4  0.92 — Irreversible, high-stakes, emotionally loaded (spec
#       §19.2 names "medical" here too). R4 never auto-executes — a
#       human always decides — so this floor does not gate execution the
#       way R0-R3's do; it gates whether a candidate option is even
#       *presented* to a household facing a relocation, a property
#       purchase, or a medical choice. A shakily-grounded option
#       materially misleads a family on something they may not be able
#       to undo, which is why this is the single strictest floor in the
#       system even though R4 is never auto-executed — "never silently
#       proceed" applies to *presenting*, not only to *acting*.

_CONFIDENCE_FLOOR: dict[RiskTier, float] = {
    RiskTier.R0_SILENT: 0.50,
    RiskTier.R1_NOTIFY: 0.60,
    RiskTier.R2_APPROVE: 0.75,
    RiskTier.R3_EXPLICIT_APPROVE: 0.88,
    RiskTier.R4_ESCALATE_ONLY: 0.92,
}


def confidence_floor(tier: RiskTier) -> float:
    """The minimum confidence a proposed action at `tier` must clear.

    Below this floor, spec §19.2 gives the caller exactly three options —
    downgrade tier, escalate, or discard — and forbids a fourth: silently
    proceeding. This function only reports the floor; enforcing it against
    a specific `contracts.agents.AgentOutput.confidence` (and raising
    `contracts.errors.LowConfidenceError` when it is not met) is the
    Confidence Arbiter's (A57, E3) job, not this module's.

    Args:
        tier: the `RiskTier` to look up.

    Returns:
        The confidence floor for `tier`, strictly increasing from R0
        (0.50) to R4 (0.92) — see the module-level comment above this
        table for the full per-tier reasoning.
    """
    return _CONFIDENCE_FLOOR[tier]


# ---------------------------------------------------------------------------
# Hard-constraint floor rule (spec §18.2 rule 2)
# ---------------------------------------------------------------------------


def apply_hard_constraint_floor(tier: RiskTier, *, hard_constraint_involved: bool) -> RiskTier:
    """Spec §18.2 rule 2, verbatim: "Hard-constraint involvement forces at
    least R2."

    A hard constraint (e.g. a documented allergy, a mobility requirement)
    being involved in a proposed action means the action can no longer be
    silent or merely notified — it must at minimum clear human approval,
    even if its base classification (`classify_risk_tier`) would otherwise
    let it execute quietly. This function is a pure floor: it never
    *downgrades* an action's strictness. An action already at R2 or above
    is returned unchanged (not bumped further just because a hard
    constraint happens to also be involved — this function encodes only
    the R2 floor rule, not a general "hard constraints mean maximum risk"
    rule the spec does not state); only R0/R1 candidates are raised to R2.

    Args:
        tier: the action's tier before this rule is applied — typically
            the result of `classify_risk_tier`, possibly already adjusted
            by a confidence-based downgrade.
        hard_constraint_involved: `True` if the action touches a HARD
            constraint (as opposed to a soft preference) — determined by
            the caller (A13 Constraint Checker's output, or equivalent),
            not by this function.

    Returns:
        `tier` unchanged if `hard_constraint_involved` is `False` or
        `tier` is already at least R2; otherwise `RiskTier.R2_APPROVE`.
    """
    if not hard_constraint_involved:
        return tier
    if tier_at_least(tier, RiskTier.R2_APPROVE):
        return tier
    return RiskTier.R2_APPROVE


__all__ = [
    "ActionTypes",
    "apply_hard_constraint_floor",
    "classify_risk_tier",
    "confidence_floor",
]

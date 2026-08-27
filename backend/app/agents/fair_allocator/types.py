"""Shared, non-agent-specific dataclasses for the Fair Allocator (A17-A21,
spec §8, PHASES.md Phase 8). Not itself an agent — these are the shapes
that flow A17 -> A18 -> (E1's `app.solvers.fair_allocation.
solve_fair_allocation`) -> A19, and separately A20/A21 monitoring the
household signal stream independently.

Kept separate from any one agent module so `interviewer_agent.py`,
`valuation_extraction_agent.py`, `fairness_verifier_explainer_agent.py`,
`renegotiation_trigger_agent.py`, and `load_monitor_agent.py` all import
the same request/finding shapes rather than each defining a slightly
different one — mirrors `app.agents.ledger.types`'s established role for
A28-A34 exactly, one phase later.

**Every result type here is deliberately narrow about what it can
express**, matching that same precedent: `ComparativePreference` (A17's
entire output) has no field that could ever hold a cost number or a task
assignment, because A17's forbidden behaviour ("computing valuations or
assigning" — spec §15.8 A17) must be structurally impossible to represent,
not merely untested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from contracts.graph_types import Constraint, NodeId

# ---------------------------------------------------------------------------
# A17 — Interviewer output shapes
# ---------------------------------------------------------------------------

CapabilityFlagName = Literal["can_drive", "can_sign", "has_bank_access", "has_medical_proxy"]
"""The four boolean capability fields on `contracts.graph_types.Person` —
the complete real set A20 can observe changing (there is no fifth boolean
capability flag on the frozen `Person` contract)."""


@dataclass(frozen=True, slots=True)
class ComparisonQuestion:
    """One adaptive comparative-elicitation question A17 has decided to
    ask next (spec §8.3.1: "would you rather do two school runs or handle
    the plumber once?"). `rationale` is the Pro-tier selection call's own
    stated reason for choosing this pair over any other remaining one —
    kept for audit, so a human reviewing the interview transcript can see
    why this comparison (and not another) was asked."""

    person_id: NodeId
    task_a_id: NodeId
    task_a_description: str
    task_b_id: NodeId
    task_b_description: str
    rationale: str


@dataclass(frozen=True, slots=True)
class ComparativePreference:
    """A17's entire output shape — a real, typed record of a comparative
    judgment a person actually made, never a cost number and never a task
    assignment (spec §15.8 A17 forbidden list: "computing valuations or
    assigning"). There is structurally no field here that could hold a
    cardinal cost — that is A18's job, over on the other side of the
    citation-like boundary this dataclass enforces."""

    person_id: NodeId
    task_a_id: NodeId
    task_b_id: NodeId
    preferred: Literal["task_a", "task_b", "tie"]
    raw_answer_text: str
    """The person's real, unmodified free-text answer — never discarded,
    matching the graph-wide "never discard the original" discipline
    (`contracts.graph_types.Constraint.original_text`'s own precedent)."""
    reasoning: str
    confidence: float


@dataclass(frozen=True, slots=True)
class NextComparisonRequest:
    """A17's input for one `select_next_comparison` call: the remaining
    candidate tasks, what has already been asked, and every preference
    collected so far this session — the Pro-tier selection call's whole
    job is choosing the most informative *unasked* pair given this
    history (e.g. never re-asking a pair whose answer is already implied
    by transitivity)."""

    person_id: NodeId
    candidate_task_ids: tuple[NodeId, ...]
    task_descriptions: dict[str, str]
    """`task_id` (as `str`) -> human-readable description — every id in
    `candidate_task_ids` must have an entry here."""
    already_asked_pairs: tuple[tuple[NodeId, NodeId], ...]
    """Unordered pairs already asked this session — a pair `(a, b)` here
    means the same as `(b, a)`; callers need not worry about order."""
    preferences_so_far: tuple[ComparativePreference, ...]


# ---------------------------------------------------------------------------
# A18 — Valuation Extraction output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedEffortSignal:
    """One real, task-linked piece of observed-completion evidence (spec
    §8.3.2 "observed completion history"; §5.5's "who actually did the
    grocery run"). Produced by `context.resolve_observed_effort_signals`
    from a real `GraphReader.effort_evidence` result plus the second
    `DISCHARGES` hop E1's Phase 8 final report named explicitly — never
    fabricated, and never present for a `PurchaseItem` this household's
    graph does not actually link to a task."""

    task_id: NodeId
    purchase_item_id: NodeId
    description: str


@dataclass(frozen=True, slots=True)
class ValuationExtractionRequest:
    """A18's input for one person's cost matrix: every real evidence
    source spec §8.3.2 names (complaints, interview answers, voice notes,
    observed history), pre-resolved by the caller — mirrors
    `app.agents.ledger.types.LeakageAssessmentRequest`'s "pre-resolved
    context, assembled by the caller" shape exactly."""

    person_id: NodeId
    allocation_cycle_id: str
    """Identifies this elicitation round for idempotency (mirrors
    `app.agents.ledger.staff_payroll_agent`'s `attendance.month` role for
    salary-obligation writes) — e.g. a date-stamped or UUID round id."""
    candidate_task_ids: tuple[NodeId, ...]
    task_descriptions: dict[str, str]
    complaint_texts: tuple[str, ...]
    comparative_preferences: tuple[ComparativePreference, ...]
    """This person's own preferences from A17 — never another person's."""
    voice_note_texts: tuple[str, ...]
    observed_effort: tuple[ObservedEffortSignal, ...]


@dataclass(frozen=True, slots=True)
class ValuationExtractionResult:
    """A18's entire output — the written `ValuationProfile`'s id plus its
    real content, for the caller (and E4's cost-matrix visualisation) to
    use without re-reading the graph. `omitted_task_ids` is the explicit,
    positive record of the "sparse matrix -> request coverage" failure
    mode (spec §15.8 A18) — never silently absent from this result."""

    valuation_profile_id: NodeId
    person_id: NodeId
    costs: dict[str, float]
    """Task id (as `str`) -> this person's real cost — sparse by
    omission, exactly matching `contracts.graph_types.ValuationProfile.
    costs`'s own contract. Never contains a fabricated placeholder for a
    task this module was not confident about."""
    omitted_task_ids: tuple[NodeId, ...]
    """Every `candidate_task_ids` entry that did NOT make it into `costs`
    — either the model never priced it, or priced it below this module's
    confidence floor. Surfaced explicitly so a caller can "request
    coverage" (spec's own failure-mode wording) for exactly these tasks."""
    elicitation_method: Literal["interview", "complaint_inference", "observed_history", "mixed"]
    reasoning: dict[str, str]
    """Task id (as `str`) -> the model's real, per-task reasoning for
    every task in `costs` — never a generic explanation."""
    confidence: float
    """Average confidence across the priced tasks in `costs`; `0.0` when
    `costs` is empty (nothing was confidently priced at all)."""
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


# ---------------------------------------------------------------------------
# A19 — Fairness Verifier / Explainer output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BundleComparison:
    """One other person's bundle, priced *only* under the envier's own
    valuation — this is what keeps A19's explanations from ever leaking
    another person's `ValuationProfile.costs` (spec §15.8 A19: "explain
    each share in that person's own valuations")."""

    other_person_id: NodeId
    other_person_task_descriptions: tuple[str, ...]
    cost_to_this_person: float
    """`sum(this person's own costs[t] for t in the other person's
    bundle)` — the envier's own opinion of the envied bundle, never the
    envied person's own valuation of it."""


@dataclass(frozen=True, slots=True)
class ShareExplanationRequest:
    """One person's real share, described entirely in terms of *their
    own* valuation — the Pro-tier explanation call's input. Never carries
    another person's cost data (see `BundleComparison`'s own docstring)."""

    person_id: NodeId
    own_task_descriptions: dict[str, str]
    """Task id (as `str`) -> description, for this person's own bundle
    only."""
    own_costs: dict[str, float]
    """Task id (as `str`) -> this person's own cost, for this person's
    own bundle only."""
    own_total_cost: float
    comparisons: tuple[BundleComparison, ...]
    ef1_holds_for_this_person: bool
    violation_detail: str | None
    """Populated only when `ef1_holds_for_this_person` is `False` — the
    real, computed reason (from `verify_ef1`), never a guess."""


@dataclass(frozen=True, slots=True)
class PersonShareExplanation:
    person_id: NodeId
    task_ids: tuple[NodeId, ...]
    total_cost_to_self: float
    explanation_text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class FairnessVerificationResult:
    """A19's entire output — both the deterministic verification half and
    the Pro-tier explanation half, kept in one result so a caller always
    sees both together (spec §8.3.4: "verify... then explain")."""

    ef1_holds: bool
    violation_count: int
    explanations: tuple[PersonShareExplanation, ...]
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


# ---------------------------------------------------------------------------
# A20 — Renegotiation Trigger output shapes
# ---------------------------------------------------------------------------

RenegotiationReasonKind = Literal["schedule_constraint_change", "capability_change"]


@dataclass(frozen=True, slots=True)
class ScheduleConstraintChangeSignal:
    """A real, new-or-changed hard `SCHEDULE`-kind `Constraint` for one
    person — the caller's job (a graph-diff watcher, out of this
    package's scope) is detecting that *something* changed; A20's job is
    judging whether it is renegotiation-worthy."""

    person_id: NodeId
    new_constraint: Constraint
    previous_constraint: Constraint | None
    """`None` when this is a genuinely new constraint, not a change to an
    existing one."""


@dataclass(frozen=True, slots=True)
class CapabilityChangeSignal:
    """A real, observed flip of one of `Person`'s four boolean capability
    fields — always renegotiation-worthy by construction (a capability
    flip is unambiguous; no model judgment is needed, unlike a schedule
    constraint's free-text severity)."""

    person_id: NodeId
    capability_name: CapabilityFlagName
    old_value: bool
    new_value: bool


@dataclass(frozen=True, slots=True)
class RenegotiationTrigger:
    """A20's entire output for one detected life event — a real, typed
    signal that a new A17-A21 elicit/extract/solve/verify cycle should
    run. **Never re-solves anything itself** — this type has no field
    that could hold an allocation, a cost, or a solver result (spec
    §15.8 A20's whole job is "monitor for life events... warranting
    re-allocation", not performing the re-allocation)."""

    trigger_id: str
    person_id: NodeId
    reason_kind: RenegotiationReasonKind
    detail: str
    detected_at: datetime
    confidence: float


@dataclass(frozen=True, slots=True)
class ConcessionCheckRequest:
    """Input for A20's deterministic concession detection: did this
    person's new bundle cost *them* (under their own current valuation)
    more than their prior bundle would have? Both bundles are priced
    under `current_costs_for_person` so the comparison is apples-to-apples
    under one consistent valuation, never mixing an old cycle's cost
    matrix with a new one."""

    person_id: NodeId
    prior_bundle_task_ids: tuple[NodeId, ...]
    new_bundle_task_ids: tuple[NodeId, ...]
    current_costs_for_person: dict[str, float]
    renegotiation_reason: str
    allocation_cycle_id: str


@dataclass(frozen=True, slots=True)
class ConcessionEvidence:
    """A20's real, computed evidence that a person accepted a costlier
    share than before — never a guess, always backed by the exact two
    bundle-cost figures that produced it."""

    person_id: NodeId
    prior_bundle_cost: float
    new_bundle_cost: float
    reasoning: str


# ---------------------------------------------------------------------------
# A21 — Load Monitor output shapes
# ---------------------------------------------------------------------------

LoadImbalanceVerdict = Literal["balanced", "creeping_imbalance", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class LoadDriftCheckRequest:
    """A21's input for one person's drift check: their expected share of
    total cost (from the last `FairAllocationResult.person_total_cost`,
    normalised by the caller) versus their real observed share of the
    household's actual completed load this window."""

    person_id: NodeId
    window: tuple[datetime, datetime]
    expected_share_of_total_cost: float
    """`person_total_cost[person_id] / sum(person_total_cost.values())`
    from the last computed allocation — this person's *intended* share."""
    observed_load: float
    """`GraphReader.load(person_id, window)` — this person's real,
    observed obligation load this window."""
    household_total_observed_load: float
    """Sum of `observed_load` across every household member in the same
    window — the caller's job to aggregate (see `context.
    household_total_load`)."""


@dataclass(frozen=True, slots=True)
class LoadImbalanceFinding:
    """A21's entire output for one person's drift check. `verdict` always
    comes from a real, evidence-backed comparison — never a guessed
    imbalance (spec §15.8 A21: "detects creeping imbalance... " backed by
    the real numbers carried on this dataclass)."""

    person_id: NodeId
    expected_share: float
    observed_share: float | None
    """`None` only when `household_total_observed_load` is `0.0` — there
    is no real observed-load signal at all this window, so no share can
    be computed (`verdict` is always `"insufficient_data"` in that case)."""
    drift: float | None
    verdict: LoadImbalanceVerdict
    reasoning: str
    confidence: float
    model_tier: Literal["flash", "deterministic"]
    """`"flash"` only when a real Gemini call narrated a `"creeping_
    imbalance"` verdict; `"balanced"`/`"insufficient_data"` verdicts make
    no model call at all (cost discipline: nothing to narrate at length
    when there is no finding — mirrors `ReconciliationAgent`'s
    deterministic-vs-pro split)."""


__all__ = [
    "BundleComparison",
    "CapabilityChangeSignal",
    "CapabilityFlagName",
    "ComparativePreference",
    "ComparisonQuestion",
    "ConcessionCheckRequest",
    "ConcessionEvidence",
    "FairnessVerificationResult",
    "LoadDriftCheckRequest",
    "LoadImbalanceFinding",
    "LoadImbalanceVerdict",
    "NextComparisonRequest",
    "ObservedEffortSignal",
    "PersonShareExplanation",
    "RenegotiationReasonKind",
    "RenegotiationTrigger",
    "ScheduleConstraintChangeSignal",
    "ShareExplanationRequest",
    "ValuationExtractionRequest",
    "ValuationExtractionResult",
]

"""Shared, non-agent-specific dataclasses for the Household Simulator
(A35-A40, spec §11, §15.8, PHASES.md Phase 11, ADR-017) — E2's
`backend/app/agents/simulator/`.

Mirrors the role `app.agents.concierge.types`/`app.agents.intention_action.
types` already play for their own packages: one place every A35-A40
module imports the same request/result shapes from, so the pipeline
(frame -> ground -> simulate [per branch, parallel] -> critique ->
calibrate -> synthesize) stays legible end to end, and so backward mode's
second entry point on A35/A39/A40 (ADR-017 decision 3) shares the exact
same shapes as forward mode rather than a parallel set.

**The seven shapes below this module's own docstring marker are frozen by
ADR-017/this phase's dispatch — exact field names, no deviation.** E4 is
coding a TypeScript mirror against these same names; a field rename here
breaks that contract silently. Every other dataclass in this file (the
various `*Request` input shapes) is this package's own implementation
detail, free to evolve, and deliberately kept separate from the frozen
seven so it is always obvious which is which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from contracts.graph_types import NodeId

from ...reasoning.gemini_client import GroundedCitation
from ...solvers.calibration_stats import CalibrationEstimate, RankedOutcome

# ---------------------------------------------------------------------------
# ADR-017 frozen shapes — do not rename/remove a field without a
# CTO-adjudicated re-freeze (E4 codes a TypeScript mirror against these
# exact names).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionFrame:
    """A35 Decision Framing's entire output for one framing pass (forward
    or backward mode — ADR-017 decision 3). `is_false_binary`/
    `unconsidered_options` are always populated for a forward-mode frame;
    a backward-mode frame (`frame_backward`) sets `is_false_binary=False`
    and `unconsidered_options=()` structurally — "assume this plan
    failed, why?" has no binary to detect and no branches to propose
    (`proposed_branch_labels=()` too), it is a single evidence-linked
    question, not a fork."""

    decision_id: NodeId
    question: str
    trigger: str
    is_false_binary: bool
    unconsidered_options: tuple[str, ...]
    proposed_branch_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """A36 Grounding/Research's entire output for one branch. `summary`
    is deliberately neutral prose — never an impact claim (spec §15.8
    A36 forbidden: "projecting consequences"; that is A37's job, using
    this result as one input among several, never A36's own words).
    `citations` is empty exactly when Google Search grounding did not
    trigger for this branch's query — a real, expected outcome, never
    backfilled with an invented source (ADR-017's "honest fallback,
    never fabricated")."""

    branch_label: str
    citations: tuple[GroundedCitation, ...]
    summary: str
    freshness_note: str


@dataclass(frozen=True, slots=True)
class BranchProjection:
    """A37 Path Simulator's entire output for exactly one branch —
    produced by a call that can see only this one branch's own context
    (spec §15.8 A37 forbidden: "comparing branches" — structurally
    impossible when the function signature never accepts another
    branch's data at all; see `path_simulator_agent.py`).

    `grounding_refs` follows the formal citation-string convention this
    phase establishes: `"<title> (<uri>) — retrieved <ISO8601>"`, built
    from `GroundingResult.citations` (see
    `path_simulator_agent.format_grounding_ref`). `blast_radius_node_ids`
    is the real, graph-derived id set `GraphReader.blast_radius_multi`
    returned for this branch's anchors — every claim in `projected_impacts`
    is expected to trace back to either this id set or a `grounding_refs`
    entry (Gate 11: "every branch claim traceable to graph data or a
    cited source")."""

    branch_id: NodeId
    label: str
    projected_impacts: dict[str, str]
    grounding_refs: tuple[str, ...]
    blast_radius_node_ids: tuple[NodeId, ...]


@dataclass(frozen=True, slots=True)
class BranchCritique:
    """A38 Consistency Critic's entire output for exactly one already-
    produced `BranchProjection` (spec §15.8 A38: "critiques *another
    agent's* output" — the pattern that works, never self-critique).
    `revised_confidence_note` is always present, even when no over-
    optimistic claim or omission was found — a clean critique still
    states, honestly, that the projection held up under adversarial
    review, rather than leaving the caller to infer a null result from
    two empty tuples."""

    branch_id: NodeId
    over_optimistic_claims: tuple[str, ...]
    omitted_second_order_effects: tuple[str, ...]
    revised_confidence_note: str


@dataclass(frozen=True, slots=True)
class DecisionBrief:
    """A40 Decision Synthesizer's entire forward-mode output. Deliberately
    has **no `recommended_branch_id`/`verdict`/choice field of any kind**
    — spec §15.8 A40's forbidden behaviour ("recommending a choice on
    emotionally-loaded family decisions") is structurally impossible to
    represent here, not merely untested; see
    `test_decision_synthesizer_agent.py::TestNoVerdictField` for the
    property-based/structural proof this project's "structurally cannot
    X" pattern demands (mirrors A32 Dispute Branch's neutral-summary
    guarantee and A23's diagnosis-only shape). `trade_offs` presents the
    real trade-offs; it never resolves them."""

    decision_id: NodeId
    branch_summaries: tuple[str, ...]
    trade_offs: tuple[str, ...]
    open_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackwardModeAnalysis:
    """A40 Decision Synthesizer's backward-mode output (ADR-017 decision
    3 — a second entry point on the same six agents, not a seventh
    agent). `assumed_failure_point` must cite specific
    `supporting_outcome_ids` — never a generic claim
    ("moves often slip") — those ids are real `Outcome` node ids drawn
    from A39's `CalibrationNarration.ranked_outcomes` for this plan's
    category, never invented. Carries the same forbidden-verdict
    discipline as `DecisionBrief`: `suggested_mitigations` are
    actionable next steps, never a "you should do X instead" choice
    between family options."""

    plan_description: str
    assumed_failure_point: str
    supporting_outcome_ids: tuple[NodeId, ...]
    confidence_note: str
    suggested_mitigations: tuple[str, ...]


# ---------------------------------------------------------------------------
# A35 Decision Framing — request shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionFramingRequest:
    """A35's input for one forward-mode framing pass. `known_household_
    context` is pre-resolved by the caller (this codebase's established
    "pre-resolved by the caller" precedent) — real facts (existing hard
    constraints, recurring obligations, staff tenure, board-exam years)
    that might reveal a real unconsidered option or expose a false
    binary; A35 itself holds no `GraphReader`."""

    household_request_text: str
    trigger: str
    proposed_branch_labels: tuple[str, ...]
    known_household_context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackwardFramingRequest:
    """A35's input for one backward-mode framing pass (`frame_backward`)
    — "take a committed plan, assume it failed" (spec §11.3). `category_tag`
    is a real `Outcome.attribution_tags` decision-category value (ADR-017:
    `"relocation"`, `"school_transition"`, `"staff_transition"`,
    `"major_purchase"`), passed straight through to A39's
    `outcome_variance(tag)` call downstream — never invented by A35."""

    plan_description: str
    category_tag: str


# ---------------------------------------------------------------------------
# A36 Grounding/Research — request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroundingRequest:
    """A36's input for one branch's external-grounding pass."""

    branch_label: str
    topic: str
    """What to actually research, e.g. "cost of living and staff
    availability in Bangalore for a mid-2026 relocation" — the real
    seed for query construction, never invented by A36 itself."""
    household_context: str
    """Short, real context A36's Pro-tier relevance-filtering pass uses
    to judge whether a search result is actually relevant to *this*
    branch's topic, e.g. "household of 4, one child in board-exam year,
    one elder on a twice-weekly dialysis schedule.\""""


# ---------------------------------------------------------------------------
# A37 Path Simulator — request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PathSimulationRequest:
    """A37's entire input for exactly one branch's independent
    simulation pass — no field here can carry another branch's data
    (spec §15.8 A37 forbidden: "comparing branches"). `candidate_anchor_ids`
    is the caller-assembled candidate pool of real node ids that might
    touch this decision's topic (`GraphReader` has no "find every entity
    touching topic X" primitive, mirroring `app.agents.concierge.
    types.ServiceDiscoveryRequest.known_provider_ids`'s identical "caller
    assembles the pool" precedent) — A37 itself does the real filtering
    (does this id actually resolve to a real, still-current Person/
    Obligation/Constraint?) before calling `blast_radius_multi`, which is
    this agent's own real "derive real anchor NodeIds from the graph"
    responsibility (PHASES.md Phase 11 E1/E2 work item)."""

    decision_id: NodeId
    branch_label: str
    branch_topic: str
    candidate_anchor_ids: tuple[NodeId, ...]
    grounding: GroundingResult | None
    blast_radius_depth: int = 2


# ---------------------------------------------------------------------------
# A38 Consistency Critic — request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CritiqueRequest:
    """A38's entire input — exactly one already-produced
    `BranchProjection`, plus enough real context to red-team it.
    `blast_radius_context` is a real, human-readable summary per node id
    in `branch_projection.blast_radius_node_ids` (see
    `context.summarize_anchor_nodes`) — the same real graph data A37 saw,
    given to A38 so its adversarial pass can check a projection's claims
    against the real breakage the graph already surfaced, not just the
    projection's own prose."""

    branch_projection: BranchProjection
    branch_topic: str
    blast_radius_context: tuple[str, ...]


# ---------------------------------------------------------------------------
# A39 Calibration — result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibrationNarration:
    """A39's entire output for one category tag. `estimate`/
    `ranked_outcomes` are exactly what `app.solvers.calibration_stats`
    computed — this agent never recomputes or overrides them (spec
    §15.8 A39: "statistics delegated to a tool"). `narrative` is the
    honest Pro-tier (or, when there is nothing at all to narrate,
    deterministic — see `calibration_agent.py`) gloss on those real
    numbers; when `estimate.is_thin_history` is `True`, `narrative` is
    guaranteed (structurally, not just by prompt) to contain
    `estimate.note` verbatim (ADR-017/spec §11.5: "insufficient history
    -> say so, never produce false precision")."""

    tag: str
    estimate: CalibrationEstimate
    ranked_outcomes: tuple[RankedOutcome, ...]
    narrative: str
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` only when there was zero history at all for this
    tag (nothing to narrate beyond the tool's own honest zero-count note)
    — mirrors `app.agents.fair_allocator.load_monitor_agent`'s established
    "nothing to narrate" precedent. `"pro"` whenever at least one real
    `Outcome` exists for this tag, thin or not."""


# ---------------------------------------------------------------------------
# A40 Decision Synthesizer — backward-mode request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BackwardSynthesisRequest:
    """A40's input for `synthesize_backward` — assembled from A35's
    backward-mode `DecisionFrame` and A39's category-matched
    `CalibrationNarration`, per ADR-017 decision 3 ("backward mode is a
    second entry point on A35/A39/A40, not a seventh agent"). Not one of
    this module's frozen seven (see module docstring) — free to evolve.

    `plan_description` is the caller's own real plan text — the same
    string it originally passed to `DecisionFramingAgent.frame_backward`
    (`BackwardFramingRequest.plan_description`) — carried here verbatim
    rather than re-derived by parsing `frame.question`'s fixed "Assume
    this plan failed — why? Plan: ..." wrapper text, so `BackwardModeAnalysis
    .plan_description` is never dependent on that wrapper's exact wording
    staying stable."""

    frame: DecisionFrame
    calibration: CalibrationNarration
    plan_description: str


__all__ = [
    "BackwardFramingRequest",
    "BackwardModeAnalysis",
    "BackwardSynthesisRequest",
    "BranchCritique",
    "BranchProjection",
    "CalibrationNarration",
    "CritiqueRequest",
    "DecisionBrief",
    "DecisionFrame",
    "DecisionFramingRequest",
    "GroundingRequest",
    "GroundingResult",
    "PathSimulationRequest",
]

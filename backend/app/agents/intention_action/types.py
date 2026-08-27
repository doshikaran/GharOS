"""Shared, non-agent-specific dataclasses for the Intention->Action
Converter (A22-A26, spec §9, PHASES.md Phase 9). Not itself an agent —
these are the shapes that flow A22 -> A23 -> A24/A25, and separately A23's
diagnosis -> a human correction -> `friction_profile` -> A26's re-diagnosis
loop.

Kept separate from any one agent module so `intention_capture_agent.py`,
`blocker_diagnosis_agent.py`, `unblocker_agent.py`,
`window_scheduling_agent.py`, `slippage_analyst_agent.py`, and
`friction_profile.py` all import the same request/finding shapes rather
than each defining a slightly different one — mirrors
`app.agents.ledger.types`/`app.agents.fair_allocator.types`'s established
role for their own packages exactly, one phase later.

**Every result type here is deliberately narrow about what it can
express**, matching that same precedent: `BlockerDiagnosis` (A23's entire
output) has no field that could hold a fetched fact, a narrowed decision,
a pre-drafted message, or a modality switch, because A23's forbidden
behaviour ("unblocking" — spec §15.9 A23) must be structurally impossible
to represent, not merely untested. Symmetrically, none of A24's result
types (`InformationFetchResult`, `DecisionNarrowingResult`,
`ModalitySwitchResult`, `FirstStepDecompositionResult`) has a `sent_at` or
send-status field of any kind — dispatching anything A24 prepares is
Phase 10's Outbound Concierge job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from contracts.graph_types import Constraint, NodeId

# ---------------------------------------------------------------------------
# Shared taxonomy — spec §9.3 Stage 2's six-type closed blocker taxonomy
# ---------------------------------------------------------------------------


class BlockerType(StrEnum):
    """The six-type taxonomy spec §9.3 names explicitly, and no others —
    a closed enum, not an open string, so "the specific obstacle" A23
    names is always one of exactly these six, never a model-invented
    seventh category."""

    INFORMATION = "information"
    """A needed fact is missing (number, account, policy, last service
    date)."""
    DECISION = "decision"
    """An unmade choice sits upstream of the task."""
    WINDOW = "window"
    """Action is only possible when the person is never free."""
    FIRST_STEP_AMBIGUITY = "first_step_ambiguity"
    """The person doesn't know the actual first action."""
    DEPENDENCY = "dependency"
    """Something else must happen first."""
    AVERSION = "aversion"
    """The person systematically avoids this *modality* (e.g. never makes
    calls) — not the task itself."""


# ---------------------------------------------------------------------------
# A22 — Intention Capture output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PassiveIntentionDetection:
    """A22's real output for one passing message found to express a
    household intention not yet an `Obligation` — spec §9.3 Stage 1's
    "a note, a passing message... or a stated goal." Never itself an
    `Obligation` write (spec §15.9 A22 forbidden: "acting directly") —
    purely a detection record for a caller (A15 Obligation Writer, or a
    human) to act on."""

    source_text: str
    """The real, unmodified message text this was detected from — never
    discarded (matches `Constraint.original_text`'s established
    precedent)."""
    person_id: NodeId | None
    """Who expressed the intention, if resolvable from context — `None`
    when the speaker is not identifiable from `source_text` alone."""
    intention_summary: str
    """A plain restatement of the intention actually expressed — never an
    embellishment or an inferred elaboration beyond what the text says."""
    suggested_title: str
    """A short, obligation-shaped title a caller could use verbatim when
    writing a real `Obligation` — never written by this agent itself."""
    confidence: float
    reasoning: str
    model_tier: Literal["flash"]
    prompt_version: str
    invocation_id: str


@dataclass(frozen=True, slots=True)
class StaleObligationDetection:
    """A22's real output for one `Obligation` found stale — spec §9.3
    Stage 1's "an OBLIGATION gone stale." Purely deterministic (see
    `intention_capture_agent._is_stale`'s docstring for the documented,
    defensible threshold) — no Gemini call backs this detection, so there
    is nothing here to hallucinate."""

    obligation_id: NodeId
    title: str
    reason: str
    """Human-readable explanation of exactly which threshold was crossed,
    e.g. "due 12 days ago with no status change since"." """
    days_stale: int
    threshold_days: int
    detected_at: datetime


# ---------------------------------------------------------------------------
# A23 — Blocker Diagnosis output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockerDiagnosisRequest:
    """A23's input for one diagnosis pass — every fact the caller has
    already resolved from the graph (dependency chain, known schedule
    facts, prior related messages), pre-resolved by the caller exactly as
    `app.agents.fair_allocator.types.ValuationExtractionRequest` and
    `app.agents.ledger.types.LeakageAssessmentRequest` already establish
    for their own packages. A23 holds no tool of any kind (spec §15.9
    A23: "no search, no draft, no write" — extended here to "no read"
    too, since every fact it reasons over arrives already resolved)."""

    obligation_id: NodeId
    person_id: NodeId
    obligation_title: str
    obligation_type: str
    status: str
    effort_estimate_minutes: int | None
    due_at: datetime | None
    must_start_by: datetime | None
    known_facts: tuple[str, ...]
    """Real, caller-resolved context: dependency-chain titles, prior
    related message excerpts, known schedule constraints in plain text —
    never fabricated by this request's caller, never elaborated on by
    A23 beyond what is given here."""
    friction_profile_summary: str | None
    """A plain-text summary of this person's existing friction profile
    for tasks like this one (see `friction_profile.summarise_for_person`)
    — `None` when no prior pattern exists yet. Helps A23 weigh a
    diagnosis against this person's own documented history without A23
    ever touching the graph itself."""
    prior_diagnosis: BlockerDiagnosis | None
    """Set only on a re-diagnosis call (spec §9.3 Stage 4: "if it slips
    again, re-diagnose — the first diagnosis may have been wrong").
    `None` for a first diagnosis."""


@dataclass(frozen=True, slots=True)
class BlockerDiagnosis:
    """A23's entire output — a real, explicit, human-readable diagnosis
    "so it can be corrected" (spec §9.4's own phrase, and PHASES.md Gate
    9's literal wording). `diagnosis_text` is first-class, never buried
    inside `reasoning` or implied only by `blocker_type` — a human reading
    only `diagnosis_text` must be able to correct it without decoding a
    confidence score."""

    obligation_id: NodeId
    person_id: NodeId
    blocker_type: BlockerType
    diagnosis_text: str
    """A complete, standalone, human-readable statement of the diagnosis
    — e.g. "This is blocked because Aarav avoids phone calls, not because
    the number is missing or the time is wrong." Never a fragment that
    only makes sense alongside `reasoning`."""
    evidence: tuple[str, ...]
    """Which of `BlockerDiagnosisRequest.known_facts` (or
    `friction_profile_summary`) actually support this diagnosis — a
    citation-like trail, never asserting something not in the given
    facts."""
    confidence: float
    considered_alternative_types: tuple[BlockerType, ...]
    """Other blocker types the model considered and rejected — real
    corrigibility support: a human reading this can see *why* it wasn't
    diagnosed as e.g. a window blocker, not just that it wasn't."""
    is_rediagnosis: bool
    superseded_diagnosis_type: BlockerType | None
    """`prior_diagnosis.blocker_type` when `is_rediagnosis` is `True` and
    this diagnosis reached a different conclusion; `None` otherwise —
    never populated when the re-diagnosis simply confirms the original
    type (that is not a supersession, it is a confirmation)."""
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str
    diagnosed_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisCorrection:
    """A real, human-issued correction to a `BlockerDiagnosis` — spec
    §9.5's "misdiagnosed blocker -> state the diagnosis explicitly;
    capture correction; feed back." Never constructed by A23 itself (A23
    holds no write tool); this is the input to `friction_profile.
    apply_diagnosis_correction`, whoever calls it (the orchestration layer
    that surfaced the diagnosis and received the human's correction)."""

    obligation_id: NodeId
    person_id: NodeId
    original_diagnosis: BlockerDiagnosis
    corrected_blocker_type: BlockerType
    correction_note: str
    """The human's own words explaining the correction — never discarded,
    never paraphrased away."""
    corrected_by: NodeId
    corrected_at: datetime


# ---------------------------------------------------------------------------
# A24 — Unblocker / Preparation output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphQuerySpec:
    """One real `contracts.repositories.GraphReader` operation the caller
    has already determined would answer an information blocker's missing
    fact — mirrors this whole codebase's "pre-resolved by the caller"
    precedent rather than asking a model to invent graph-query arguments
    it could hallucinate (an unresolvable node id, a nonexistent edge
    type). `operation` must be one of `app.tools.graph_read_tool`'s
    `_OPERATIONS`; `args` are that operation's real keyword arguments."""

    operation: str
    args: dict[str, object]


@dataclass(frozen=True, slots=True)
class InformationFetchRequest:
    obligation_id: NodeId
    person_id: NodeId
    missing_fact_description: str
    query: GraphQuerySpec


@dataclass(frozen=True, slots=True)
class InformationFetchResult:
    """A24's real output for an information blocker — Gate 9's "Information
    blocker -> fact fetched." `fetched=False` (never a fabricated
    `fact_text`) whenever the real graph query returns nothing."""

    obligation_id: NodeId
    missing_fact_description: str
    fetched: bool
    fact_text: str | None
    confidence: float
    model_tier: Literal["flash"]
    prompt_version: str | None
    invocation_id: str


@dataclass(frozen=True, slots=True)
class DecisionNarrowingRequest:
    obligation_id: NodeId
    person_id: NodeId
    decision_summary: str
    known_options: tuple[str, ...]
    known_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionNarrowingResult:
    """A24's real output for a decision blocker — Gate 9's "Decision
    blocker -> narrowed to binary." `option_a`/`option_b` are always two
    real, distinct, mutually exclusive options — never the decision left
    open, and never a third "it depends" escape hatch (that would not be
    narrowing)."""

    obligation_id: NodeId
    option_a: str
    option_b: str
    framing_text: str
    reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


AversionModality = Literal["call", "message", "in_person", "email", "app_form"]
"""The real modalities a household task can be conducted through — closed
so `switch_modality`'s output can be checked (`to_modality != from_modality`)
without guessing at free-text spelling variance."""


@dataclass(frozen=True, slots=True)
class ModalitySwitchRequest:
    obligation_id: NodeId
    person_id: NodeId
    avoided_modality: AversionModality
    task_summary: str
    counterparty_name: str
    known_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModalitySwitchResult:
    """A24's real output for an aversion blocker — Gate 9's "Aversion
    blocker -> modality switched." `to_modality` is always a real,
    different modality than `from_modality` — enforced in code, not just
    prompted for (`unblocker_agent.UnblockerAgent.switch_modality` raises
    if the model echoes the same modality back)."""

    obligation_id: NodeId
    from_modality: AversionModality
    to_modality: AversionModality
    pre_drafted_text: str
    """The real, ready-to-review replacement communication — draft only,
    no send/dispatch field anywhere on this type (see module docstring)."""
    reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


@dataclass(frozen=True, slots=True)
class FirstStepDecompositionRequest:
    obligation_id: NodeId
    person_id: NodeId
    task_summary: str
    known_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FirstStepDecompositionResult:
    """A24's real output for a first-step-ambiguity blocker — a single,
    concrete, unambiguous next physical action, never a restatement of
    the whole task."""

    obligation_id: NodeId
    first_action_text: str
    estimated_minutes: int | None
    reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


# ---------------------------------------------------------------------------
# A25 — Window Scheduling output shapes
# ---------------------------------------------------------------------------


class AvailabilityVerdict(StrEnum):
    """The real, closed verdict set `schedule_parsing`'s deterministic
    overlap check can reach for one person against one candidate window —
    ADR-015's hard/soft distinction made into a checkable enum rather
    than a free-text description."""

    AVAILABLE = "available"
    HARD_BLOCKED = "hard_blocked"
    SOFT_AVOID = "soft_avoid"
    CANNOT_DETERMINE = "cannot_determine"
    """Every `SCHEDULE`-kind constraint attached to this person was
    unparseable against ADR-015's formal schema (malformed or legacy) —
    never silently treated as `AVAILABLE`."""


CounterpartyAvailabilityVerdict = Literal["available", "unavailable", "cannot_determine"]
HistoricalLikelihoodVerdict = Literal["likely", "unlikely", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class CounterpartyWindowVerdict:
    """One candidate window's real availability verdict against a
    provider's free-text `availability_notes` — a single Pro/Flash call
    evaluates every candidate window for one provider at once (real cost
    discipline: one call per provider per scheduling attempt, not one per
    candidate window)."""

    window: tuple[datetime, datetime]
    verdict: CounterpartyAvailabilityVerdict
    reasoning: str


@dataclass(frozen=True, slots=True)
class CounterpartyAvailabilityResult:
    """A25's real output for interpreting one `Provider.availability_notes`
    free-text string against every candidate window — Flash for the clean
    case, Pro-tier fallback for messy/ambiguous text (spec §15.9 A25:
    "Flash with Pro-tier fallback")."""

    provider_id: NodeId
    per_window: tuple[CounterpartyWindowVerdict, ...]
    confidence: float
    model_tier: Literal["flash", "pro"]
    escalated_to_pro: bool
    prompt_version: str
    invocation_id: str


@dataclass(frozen=True, slots=True)
class HistoricalLikelihoodResult:
    """A25's real, evidence-backed judgment of whether this household's
    own history suggests a candidate window is actually likely to result
    in completion — spec §9.5's "use observed completion patterns, not
    stated preferences." Always backed by real `Pattern`/`Outcome`
    evidence counts; never a guessed likelihood."""

    person_id: NodeId
    obligation_id: NodeId
    likelihood: HistoricalLikelihoodVerdict
    reasoning: str
    window_blocker_pattern_support: int
    """The real `support_count` of this person's `window`-type friction
    `Pattern`, if one exists — `0` when no such pattern is on file yet."""
    outcome_count: int
    """How many real `Outcome`s (`GraphReader.history`) were available
    for this obligation — `0` contributes to an `"insufficient_data"`
    verdict, never a guessed one."""


@dataclass(frozen=True, slots=True)
class WindowFindingRequest:
    """A25's input for evaluating one obligation's candidate windows —
    every real, caller-resolved fact this agent needs (this codebase's
    established "pre-resolved by the caller" precedent, applied to A25's
    own subgraph reads exactly as `app.agents.fair_allocator.context.
    resolve_observed_effort_signals` already establishes for A18)."""

    obligation_id: NodeId
    person_id: NodeId
    obligation_kind_description: str
    candidate_windows: tuple[tuple[datetime, datetime], ...]
    person_schedule_constraints: tuple[Constraint, ...]
    provider_id: NodeId | None
    provider_availability_notes: str | None
    window_blocker_pattern_support: int
    outcome_count: int


@dataclass(frozen=True, slots=True)
class WindowCandidateEvaluation:
    window: tuple[datetime, datetime]
    person_availability: AvailabilityVerdict
    counterparty_availability: CounterpartyAvailabilityVerdict | None
    historical_likelihood: HistoricalLikelihoodVerdict
    overall_recommended: bool
    reasoning: str


@dataclass(frozen=True, slots=True)
class WindowFindingResult:
    """A25's entire output — spec §9.3 Stage 3/4's "find a window where
    person AND counterparty are available AND historically likely" made
    into one real, rankable result. `best_window` is `None` only when no
    candidate cleared the hard-block/unavailable exclusion (see
    `window_scheduling_agent._rank_candidates`'s docstring) — never a
    fallback guess."""

    obligation_id: NodeId
    person_id: NodeId
    evaluations: tuple[WindowCandidateEvaluation, ...]
    best_window: tuple[datetime, datetime] | None
    confidence: float
    model_tier: Literal["deterministic", "flash", "pro"]


# ---------------------------------------------------------------------------
# A26 — Slippage Analyst output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnblockingAttempt:
    """One real, historical attempt to unblock this same obligation —
    A26's whole input is a chronological record of these, never a bare
    failure count (spec §9.5: "on repeat failure, re-diagnose... the
    first diagnosis may have been wrong" needs the actual prior
    diagnoses, not just a number)."""

    attempt_number: int
    diagnosis: BlockerDiagnosis
    action_taken: str
    outcome: Literal["failed", "succeeded"]
    attempted_at: datetime


@dataclass(frozen=True, slots=True)
class DelegateCandidate:
    """One real, capability-eligible `Person` the caller has already
    resolved as a plausible delegate — pre-resolved exactly like
    `WindowFindingRequest.person_schedule_constraints`, never invented by
    the model (see `slippage_analyst_agent.SlippageAnalystAgent.analyze`'s
    validation: a `"delegate"` option naming anyone outside this tuple is
    rejected)."""

    person_id: NodeId
    display_name: str
    relevant_capability_note: str


@dataclass(frozen=True, slots=True)
class SlippageAnalysisRequest:
    obligation_id: NodeId
    person_id: NodeId
    obligation_title: str
    attempts: tuple[UnblockingAttempt, ...]
    eligible_delegates: tuple[DelegateCandidate, ...]
    market_rate_hint: str | None
    """A real, caller-supplied hint about what paying someone else for
    this kind of task typically costs (e.g. from `Provider.price_band`)
    — `None` when no such data exists. Never fabricated by this module or
    the model when absent (see `EscalationOption.estimated_cost`'s own
    docstring)."""


@dataclass(frozen=True, slots=True)
class SlippageReDiagnosis:
    """A26's real re-diagnosis — explicitly considers that
    `attempts[-1].diagnosis` (and every prior one) may have been wrong,
    per spec §9.3 Stage 4's own framing, never a rubber-stamp repeat of
    the same type without reconsideration."""

    likely_blocker_type: BlockerType
    reasoning: str
    confidence: float
    changed_from_prior: bool


class EscalationOptionKind(StrEnum):
    DROP = "drop"
    DELEGATE = "delegate"
    PAY = "pay"


@dataclass(frozen=True, slots=True)
class EscalationOption:
    """One real, concrete option — never a vague "this keeps failing"
    message with nothing actionable attached (spec §9.5's own failure
    mode, and PHASES.md Gate 9's "repeat slippage escalates with real
    options")."""

    kind: EscalationOptionKind
    description: str
    candidate_person_id: NodeId | None
    """Populated only for `kind == DELEGATE`, and only with an id drawn
    from `SlippageAnalysisRequest.eligible_delegates` — never invented."""
    estimated_cost: float | None
    """Populated only for `kind == PAY`, and only when
    `SlippageAnalysisRequest.market_rate_hint` gave this module something
    real to ground a number in — `None` otherwise (never a fabricated
    figure this module has no evidence for)."""


@dataclass(frozen=True, slots=True)
class SlippageAnalysisResult:
    obligation_id: NodeId
    person_id: NodeId
    attempt_count: int
    threshold: int
    escalation_triggered: bool
    re_diagnosis: SlippageReDiagnosis | None
    escalation_options: tuple[EscalationOption, ...]
    message_text: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str


__all__ = [
    "AversionModality",
    "AvailabilityVerdict",
    "BlockerDiagnosis",
    "BlockerDiagnosisRequest",
    "BlockerType",
    "CounterpartyAvailabilityResult",
    "CounterpartyAvailabilityVerdict",
    "CounterpartyWindowVerdict",
    "DecisionNarrowingRequest",
    "DecisionNarrowingResult",
    "DelegateCandidate",
    "DiagnosisCorrection",
    "EscalationOption",
    "EscalationOptionKind",
    "FirstStepDecompositionRequest",
    "FirstStepDecompositionResult",
    "GraphQuerySpec",
    "HistoricalLikelihoodResult",
    "HistoricalLikelihoodVerdict",
    "InformationFetchRequest",
    "InformationFetchResult",
    "ModalitySwitchRequest",
    "ModalitySwitchResult",
    "PassiveIntentionDetection",
    "SlippageAnalysisRequest",
    "SlippageAnalysisResult",
    "SlippageReDiagnosis",
    "StaleObligationDetection",
    "UnblockingAttempt",
    "WindowCandidateEvaluation",
    "WindowFindingRequest",
    "WindowFindingResult",
]

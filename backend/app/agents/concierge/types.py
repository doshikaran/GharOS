"""Shared, non-agent-specific dataclasses for the Outbound Concierge (A50-A56,
spec §13, PHASES.md Phase 10).

Mirrors the role `app.agents.ledger.types` / `app.agents.fair_allocator.types`
already play for their own packages: one place every A50-A56 module imports
the same request/result shapes from, so the pipeline (discover -> rank ->
brief -> [approval] -> call -> verify -> [book]) stays legible end to end.

**This module also carries the three frozen E2/E3 handoff shapes for this
phase** (`ProviderCandidate`, `CallBrief`, `CallOutcomeReport`) — the exact
field lists this phase's dispatch froze so E2's A52/A53/A55 and E3's
A51/A54 agree without live coordination. Both roles' agents import these
three from here rather than each defining their own copy — this file is
the single shared seam `backend/app/agents/concierge/` needs, matching the
one-`types.py`-per-package convention already established by `ledger/` and
`fair_allocator/`. If a role's dispatch runs and finds this file already
present with these three shapes intact, extend it (add that role's own
request/result types below) rather than redefining the shared three.

E3 (this phase's author of this file) owns everything below the "shared
handoff shapes" section that A51/A54/A56 need; E2 owns everything A50/A52/
A53/A55 need and is expected to add its own request/result dataclasses
here alongside these, never editing the three handoff shapes' field lists
(frozen by this phase's dispatch instructions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import AgentId, NodeId

# ---------------------------------------------------------------------------
# Frozen E2/E3 handoff shapes (this phase's dispatch contract — do not
# change field names/types without a CTO-adjudicated re-freeze)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    """A51's output (this file's E3 half), consumed by E2's A52 Provider
    Ranking. `provider_id` is either a NEW candidate not yet written to
    the graph (freshly discovered this search — `is_existing_household_
    provider=False`) or a real, already-graph-resident Provider's id
    (`is_existing_household_provider=True`, so A52's prior-experience
    weighting can walk real `booked_with` / `completes_into` history for
    it)."""

    provider_id: NodeId
    name: str
    category: str
    rating: float | None
    distance_km: float | None
    availability_notes: str | None
    price_band: str | None
    specialisations: tuple[str, ...]
    is_existing_household_provider: bool


@dataclass(frozen=True, slots=True)
class CallBrief:
    """E2's A53 Call Planner output, consumed by A54 (this file's E3
    half). `date_range` and `price_ceiling` are the authorised bounds the
    call may never agree outside of; `disclosable_facts` and
    `must_not_answer` are the exact scope of what A54 may reveal or must
    escalate on rather than guess."""

    target_provider_id: NodeId
    person_id: NodeId
    objective: str
    date_range: tuple[datetime, datetime]
    price_ceiling: float | None
    disclosable_facts: tuple[str, ...]
    must_not_answer: tuple[str, ...]
    preferred_slots: tuple[datetime, ...]
    fallback_acceptable: bool


@dataclass(frozen=True, slots=True)
class CallOutcomeReport:
    """A54's output (this file's E3 half), consumed by E2's A55
    Confirmation Verifier. `disclosure_given` is always `True` — see
    `voice_call_agent.py`'s module docstring for why this is structurally
    guaranteed, never merely asserted here."""

    call_id: str
    target_provider_id: NodeId
    transcript_source_document_id: NodeId
    disclosure_given: bool
    claimed_slot: datetime | None
    claimed_outcome_summary: str
    out_of_bounds_encountered: bool
    requires_human_callback: bool


# ---------------------------------------------------------------------------
# A51 Service Discovery — request/result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceDiscoveryRequest:
    """A51's input. `known_provider_ids` is the caller-assembled candidate
    pool of already-graph-resident Provider ids worth checking against
    `category` — mirrors `app.arbitration.escalation_agent.EscalationAgent.
    route`'s established "GraphReader has no enumerate-all primitive, so
    the caller assembles the pool" precedent (`contracts.repositories.
    GraphReader` has no "list every PROVIDER" operation any more than it
    has "list every PERSON"). `min_new_candidates` is how many *additional*
    freshly-discovered candidates to produce when existing coverage for
    `category` is thin — 0 is a legitimate value (household already has
    enough real history in this category)."""

    category: str
    location_context: str
    known_provider_ids: tuple[NodeId, ...]
    min_new_candidates: int = 2


@dataclass(frozen=True, slots=True)
class ServiceDiscoveryResult:
    candidates: tuple[ProviderCandidate, ...]
    model_tier: Literal["flash", "deterministic"]
    """Honest per-run record of whether a live Gemini call actually
    happened this run (mirrors `app.agents.ledger.types.
    ReconciliationRunResult.model_tier`'s identical convention) —
    `"deterministic"` when `known_provider_ids` already covered
    `min_new_candidates` and no synthetic-discovery call was made."""
    prompt_version: str | None
    discovery_source: Literal["synthetic_directory"]
    """Named explicitly, always, per this phase's own honesty requirement:
    no real Places/Maps/business-search API is integrated in this
    codebase (checked directly before writing this module) — every new
    candidate here comes from `app.tools.provider_search_tool.
    ProviderSearchTool`'s documented, honestly-labeled synthetic
    directory, never a live external search."""
    invocation_id: str


# ---------------------------------------------------------------------------
# Sandbox counterparty — persona, state, and per-turn signal
# ---------------------------------------------------------------------------


class CounterpartyVariant(StrEnum):
    """The four configurable branch-testing personas ADR-016/this phase's
    dispatch names explicitly."""

    COOPERATIVE = "cooperative"
    FIRST_PREFERRED_SLOT_UNAVAILABLE = "first_preferred_slot_unavailable"
    ASKS_OUT_OF_SCOPE_QUESTION = "asks_out_of_scope_question"
    HOSTILE_TO_AUTOMATED_CALLERS = "hostile_to_automated_callers"


@dataclass(frozen=True, slots=True)
class CounterpartyPersona:
    """The sandbox counterparty's own internal state — real, independent
    of `CallBrief`, per ADR-016 ("its own persona... its own state"). A54
    never reads this directly; it only ever sees `CounterpartyTurnSignal`s
    produced *from* it, exactly as a real caller would only hear what the
    other side of the phone call says."""

    variant: CounterpartyVariant
    clinic_name: str
    available_slots: tuple[datetime, ...]
    """The slots this persona will genuinely agree to. For
    `FIRST_PREFERRED_SLOT_UNAVAILABLE`, deliberately excludes whatever the
    test wires as the brief's first preferred slot."""
    out_of_scope_question: str | None
    """Only set for `ASKS_OUT_OF_SCOPE_QUESTION` — the literal question
    text this persona asks once, e.g. "What's the patient's date of birth
    for our file?" — a real question a real front desk might ask, that a
    `CallBrief.disclosable_facts` list may or may not cover."""


@dataclass(frozen=True, slots=True)
class CounterpartyTurnSignal:
    """One turn of the sandbox counterparty's real, independently-reasoned
    response — `sandbox_counterparty.SandboxCounterparty.respond`'s
    output. `utterance` is genuinely LLM-generated; every other field is
    a structured signal the same call extracts, so A54's bounds/branch
    logic never has to re-parse free text to decide what happened."""

    utterance: str
    offered_slot: datetime | None
    declines_call: bool
    """True only for `HOSTILE_TO_AUTOMATED_CALLERS` — "detect hostility,
    abandon gracefully" (spec §13.6)."""
    asks_question: str | None
    quoted_price: float | None = None
    """A price this turn genuinely quoted (spec §13.4's "quote-gathering
    mode"), if any — checked against `CallBrief.price_ceiling` exactly
    the way `offered_slot` is checked against `date_range` (see
    `voice_call_agent._decide_next_action`). Defaults to `None` (added
    after the other four fields, backward compatible with every existing
    `CounterpartyTurnSignal(...)` call site) — none of this phase's four
    reference persona variants quote a price live (a routine dental
    booking has no natural mid-call price-quote turn), so this field
    stays `None` for them; the mechanism is still real and tested
    directly, for the benefit of a future quote-gathering persona."""


# ---------------------------------------------------------------------------
# A54 Voice Call Agent — in-call conversation shapes
# ---------------------------------------------------------------------------

CallSpeaker = Literal["caller", "counterparty"]


@dataclass(frozen=True, slots=True)
class CallTurn:
    speaker: CallSpeaker
    utterance: str
    turn_index: int


class CallerAction(StrEnum):
    """The finite set of things A54's deterministic decision layer may do
    next — never open-ended free text the model could smuggle an
    out-of-bounds agreement or a guessed answer into (see
    `voice_call_agent.py`'s module docstring)."""

    REQUEST_SLOT = "request_slot"
    ACCEPT_SLOT = "accept_slot"
    DECLINE_OUT_OF_BOUNDS_CALLBACK = "decline_out_of_bounds_callback"
    TAKE_MESSAGE_ESCALATE = "take_message_escalate"
    END_CALL_SUCCESS = "end_call_success"
    END_CALL_HOSTILE = "end_call_hostile"
    END_CALL_EXHAUSTED = "end_call_exhausted"


@dataclass(frozen=True, slots=True)
class CallerTurnDecision:
    """One deterministic decision for what the caller (A54) does next,
    already bounds-checked by code before any phrasing call runs — see
    `voice_call_agent._decide_next_action`."""

    action: CallerAction
    target_slot: datetime | None


@dataclass(frozen=True, slots=True)
class CallConversationResult:
    """`voice_call_agent.VoiceCallConversationEngine.run_conversation`'s
    output — everything `app.arbitration.voice_call_tool.VoiceCallTool`
    needs to write the transcript and assemble a `CallOutcomeReport`,
    minus the fields only the gated tool itself can populate
    (`call_id`, `transcript_source_document_id`)."""

    turns: tuple[CallTurn, ...]
    claimed_slot: datetime | None
    claimed_outcome_summary: str
    out_of_bounds_encountered: bool
    requires_human_callback: bool


# ---------------------------------------------------------------------------
# A56 Fallback Coordinator — decision shapes
# ---------------------------------------------------------------------------


class FallbackAction(StrEnum):
    RETRY = "retry"
    WEB_BOOKING_FALLBACK = "web_booking_fallback"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class FallbackEscalationPayload:
    """Everything a downstream, non-agent dispatcher
    (`app.events.concierge_fallback_dispatcher`, outside
    `backend/app/agents/`) needs to build a real
    `app.arbitration.types.EscalationContext` and call
    `EscalationAgent.route()` — deliberately built from only
    `contracts.actions`/`contracts.graph_types` types (never
    `app.arbitration`), so `FallbackCoordinatorAgent`'s own module has
    zero import path into `app.arbitration`, exactly like every other
    module under `backend/app/agents/` (`test_action_construction_
    boundary.py`'s `TestNoAgentImportsArbitration` — this is not a
    convention, it is a structurally enforced, tested boundary; mirrors
    `app.events.followup_scan.FollowUpDecision`'s identical Phase 7
    precedent for A31, which reused the same "decide as the agent,
    dispatch as a separate events-layer module" split for the same
    reason)."""

    action_type: str
    summary: str
    risk_tier: RiskTier
    evidence_bundle: EvidenceBundle
    related_node_id: NodeId | None


@dataclass(frozen=True, slots=True)
class FallbackDecision:
    action: FallbackAction
    reasoning: str
    retry_after: datetime | None
    """Set only when `action is FallbackAction.RETRY` — when the next
    attempt is authorised to happen."""
    escalation_payload: FallbackEscalationPayload | None
    """Set only when `action is FallbackAction.ESCALATE` — the real
    escalation has not happened yet at this point; `app.events.
    concierge_fallback_dispatcher.dispatch_fallback_decision` is what
    actually calls `EscalationAgent.route()` from this payload and
    returns the real `EscalationRouting`."""


# ---------------------------------------------------------------------------
# A50 Requirement Clarifier — request/result shapes (E2)
# ---------------------------------------------------------------------------


class UrgencyLevel(StrEnum):
    """Spec §13.2 Step 1: "if pain is reported -> urgency escalates ->
    the search prioritises earliest availability over rating." A closed,
    two-value taxonomy — there is no intermediate tier."""

    ROUTINE = "routine"
    ELEVATED = "elevated"


@dataclass(frozen=True, slots=True)
class GraphKnownFact:
    """One fact about this request the household graph already answered
    — produced by `context.resolve_known_facts`'s real, structural
    graph-first check, never by A50 itself. A50 is never even shown a
    requirement the graph already answered as something it could ask
    about (spec §15.10 A50 forbidden list: "asking what the graph
    already knows")."""

    field: str
    """The requirement-checklist key this fact answers, e.g.
    `"last_visit_date"` — one of `context.SERVICE_CATEGORY_REQUIREMENTS`'s
    real entries."""
    value: str
    source: str
    """Human-readable provenance of the real graph read that produced
    this, e.g. `"neighbours(obligation-123, BOOKED_WITH)"` — audit trail
    for why this was never asked about."""


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    """A50's input for one clarification pass. `known_facts` and
    `candidate_unknowns` are both pre-resolved by the caller via
    `context.resolve_known_facts` — this codebase's established
    "pre-resolved by the caller" precedent
    (`app.agents.intention_action.types.BlockerDiagnosisRequest.
    known_facts` is the exact prior-phase analogue) — A50 itself holds no
    `GraphReader` and performs no graph read of its own."""

    household_request_text: str
    person_id: NodeId
    service_category: str
    known_facts: tuple[GraphKnownFact, ...]
    candidate_unknowns: tuple[str, ...]
    """Requirement-checklist keys the graph-first check could NOT
    resolve — the *only* things A50 is structurally permitted to propose
    a question about (see `requirement_clarifier_agent.
    RequirementClarifierAgent._parse_questions`'s validation)."""


@dataclass(frozen=True, slots=True)
class ClarifyingQuestion:
    """One real question A50 decided is worth asking — always targeting
    a real `ClarificationRequest.candidate_unknowns` entry, never an
    invented one."""

    text: str
    targets_unknown: str
    decision_relevance: str
    """Why this candidate made the cut into the top
    `requirement_clarifier_agent.MAX_CLARIFYING_QUESTIONS` — real
    corrigibility support: a human reading this can see why this
    question (and not another genuinely-unknown fact) was asked."""


@dataclass(frozen=True, slots=True)
class ClarificationResult:
    """A50's entire output. `questions` is never longer than
    `requirement_clarifier_agent.MAX_CLARIFYING_QUESTIONS` — enforced in
    code by truncation, never left to the model's own restraint (Gate 10:
    "'Book a dentist' asks <=2 questions"). Every
    `ClarificationRequest.candidate_unknowns` entry that did not become a
    question ends up in `assumptions` instead — never silently dropped."""

    person_id: NodeId
    service_category: str
    resolved_from_graph: tuple[GraphKnownFact, ...]
    """Echoes `ClarificationRequest.known_facts` back for a caller/UI
    that only has this result, not the original request, to display
    "already known from your household" alongside the question(s)."""
    questions: tuple[ClarifyingQuestion, ...]
    assumptions: tuple[str, ...]
    urgency: UrgencyLevel
    urgency_reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str
    clarified_at: datetime


# ---------------------------------------------------------------------------
# A52 Provider Ranking — request/result shapes (E2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderReliabilitySignal:
    """Real prior-household-experience evidence for one existing
    provider, resolved via `context.resolve_reliability_signal`'s walk of
    `booked_with` (OBLIGATION -> PROVIDER) then that obligation's
    `completes_into` OUTCOME, reading `Outcome.attribution_tags` against
    ADR-016's formal vocabulary (`"no_show"`, `"on_time"`,
    `"rescheduled"`, `"unresponsive_to_automated_caller"`) — never
    free-text pattern-matching."""

    provider_id: NodeId
    no_show_count: int
    on_time_count: int
    rescheduled_count: int
    unresponsive_count: int
    total_outcomes_considered: int


@dataclass(frozen=True, slots=True)
class RankingContext:
    """Every real, caller-resolved fact A52's deterministic scoring pass
    needs beyond `ProviderCandidate` itself — mirrors this codebase's
    "pre-resolved by the caller" precedent for whatever needs a second
    graph hop or a separate interpretation step this package does not
    re-implement (earliest-availability interpretation of
    `Provider.availability_notes` free text is A25's established job, not
    re-built here)."""

    urgency: UrgencyLevel
    provider_earliest_offset_days: dict[NodeId, float]
    """Provider id -> real number of days until its earliest offered
    slot, for every candidate this was resolvable for. A provider absent
    from this dict contributes a neutral (not penalised) availability
    score — "unknown" is never treated as "unavailable"."""
    reliability_by_provider: dict[NodeId, ProviderReliabilitySignal]
    """Provider id -> real prior-experience signal, populated only for
    `ProviderCandidate.is_existing_household_provider` entries with
    actual `Outcome` history on file (see `context.
    resolve_reliability_signal`'s own `None`-return contract)."""


@dataclass(frozen=True, slots=True)
class RankedProvider:
    """One provider's real, explainable rank — spec §15.10 A52's own
    "outputs: ranked list with reasons" / Gate 10's "ranking explainable
    -> the user sees why #1 is #1", made concrete: `reasons` is never
    empty and never generic, and `score_components` is the full,
    transparent breakdown behind `score` (forbidden: opaque ranking —
    there is no field here that could hold a rank with no stated
    reason)."""

    provider_id: NodeId
    name: str
    rank: int
    """1-based; `1` is the top recommendation."""
    score: float
    reasons: tuple[str, ...]
    """Real, specific, grounded reasons — e.g. "rated 4.8/5", "1.2 km
    away", "previously no-showed on file — demoted" — never a generic
    "good rating"."""
    demoted_for_reliability: bool
    """`True` only when a real `no_show_count > 0` signal was found for
    this provider — Gate 10's own literal test case."""
    score_components: dict[str, float]
    """The full weighted-component breakdown (`rating`, `distance`,
    `availability`, `price`, `reliability`) that produced `score` —
    published alongside `reasons`, never hidden."""


@dataclass(frozen=True, slots=True)
class ProviderRankingResult:
    """A52's entire output. `ranked`'s order comes ONLY from the
    deterministic `ranking.rank_candidates` pass — `narrative` is a
    Pro-tier natural-language gloss on that already-final order, and can
    never change it (see `provider_ranking_agent.ProviderRankingAgent.
    rank`'s docstring)."""

    service_category: str
    person_id: NodeId
    ranked: tuple[RankedProvider, ...]
    urgency: UrgencyLevel
    narrative: str
    """A short, natural-language explanation of why #1 is #1, grounded
    only in the real facts already on `ranked` — the deterministic
    `reasons`/`score_components` fields remain the authoritative
    explanation; this is a readability gloss, never a replacement."""
    confidence: float
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` only when `ranked` was empty (no candidates to
    narrate at all) — mirrors `app.agents.fair_allocator.
    load_monitor_agent`'s "nothing to narrate" precedent."""
    prompt_version: str
    invocation_id: str
    ranked_at: datetime


# ---------------------------------------------------------------------------
# A53 Call Planner — request/result shapes (E2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizedBounds:
    """The household's real, human-approved bounds for this call —
    sourced from the request that triggered the concierge flow, never
    invented by A53 itself (spec §15.10 A53 forbidden list: "setting
    bounds beyond what the human approved"). A53 copies every field of
    this verbatim onto the `CallBrief` it produces; see
    `call_planner_agent.CallPlannerAgent.plan`'s docstring for the
    structural guarantee that no model output can override any of
    these."""

    date_range: tuple[datetime, datetime]
    price_ceiling: float | None
    preferred_slots: tuple[datetime, ...]
    fallback_acceptable: bool


@dataclass(frozen=True, slots=True)
class CallPlanningRequest:
    """A53's input for one `CallBrief` — every real, caller-resolved
    fact this planning pass needs, mirroring this codebase's established
    "pre-resolved by the caller" precedent."""

    target_provider_id: NodeId
    target_provider_name: str
    person_id: NodeId
    person_display_name: str
    service_category: str
    objective_hint: str
    """Plain-language description of what is being requested, e.g. from
    the original household request text or `ClarificationResult` — the
    real seed A53's Pro-tier phrasing pass works from, never invented by
    A53 itself."""
    authorized_bounds: AuthorizedBounds
    disclosable_facts: tuple[str, ...]
    """Real, caller-approved facts this call may reveal — copied
    verbatim onto `CallBrief.disclosable_facts`, never expanded by A53."""
    sensitive_topics: tuple[str, ...]
    """Caller/domain-supplied topics this call must never address, in
    addition to `call_planner_agent._DEFAULT_MUST_NOT_ANSWER`'s
    category-appropriate defaults."""


@dataclass(frozen=True, slots=True)
class CallPlanningResult:
    """A53's entire output — the real `CallBrief` (the frozen handoff
    shape E3's A54 consumes) plus tracing metadata that does not belong
    on `CallBrief` itself."""

    brief: CallBrief
    objective_reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str
    planned_at: datetime


# ---------------------------------------------------------------------------
# A55 Confirmation Verifier — request/result shapes (E2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    """The deterministic core of A55's judgment — `verification.
    verify_call_outcome`'s entire output. Structurally incapable of being
    influenced by a model response: no field here is ever populated from
    parsed Gemini JSON (see `confirmation_verifier_agent.
    ConfirmationVerifierAgent.verify`'s docstring for the full structural
    argument)."""

    verified: bool
    discrepancies: tuple[str, ...]
    """Empty only when `verified` is `True`. Every entry is a real,
    specific mismatch against the original `CallBrief` — never a vague
    "something looks off"."""
    requires_human_callback: bool


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """A55's entire output. `verified` traces back ONLY to
    `VerificationVerdict.verified` (via the deterministic structural
    check, optionally narrowed further — never widened — by a Pro-tier
    semantic-plausibility cross-check) — this is Gate 10's single most
    safety-critical guarantee, made structural rather than conventional
    (see `confirmation_verifier_agent`'s module docstring). Deliberately
    plain/primitive-shaped (not `VerifiedBooking`) so
    `app.tools.booking_write_tool.verified_booking_from_verification` (or
    whatever E3 orchestration wires this into) can pull exactly the
    fields it needs without importing this module's full agent-output
    envelope."""

    call_id: str
    target_provider_id: NodeId
    verified: bool
    discrepancies: tuple[str, ...]
    requires_human_callback: bool
    explanation: str
    confidence: float
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` when the structural check alone already failed
    (nothing to narrate — the discrepancy list already is the
    explanation, and no Gemini call is made at all: cost discipline mirrors
    `app.agents.fair_allocator.load_monitor_agent`'s "nothing to narrate"
    precedent). `"pro"` only when the structural check passed and a real
    semantic cross-check ran."""
    prompt_version: str
    invocation_id: str
    verified_at: datetime


# ---------------------------------------------------------------------------
# The graph-write boundary — "verified, or it does not exist" (see
# `app.tools.booking_write_tool` for the full rationale)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifiedBooking:
    """The *only* shape `app.tools.booking_write_tool.BookingWriteTool`
    accepts. There is no `verified: bool` field here to set carelessly —
    the only way to legitimately construct one is `app.tools.
    booking_write_tool.verified_booking_from_verification`, which itself
    raises `BookingNotVerified` given anything short of a real, positive
    verification. If a `VerifiedBooking` instance exists, verification
    already happened; the type itself is the proof.

    Deliberately built from primitive fields (not by importing E2's A55
    `VerificationResult` type) — see `booking_write_tool.py`'s module
    docstring for why this is a Phase-10 boundary judgment call, not an
    oversight.
    """

    call_id: str
    obligation_id: NodeId
    person_id: NodeId
    target_provider_id: NodeId
    transcript_source_document_id: NodeId
    confirmed_slot: datetime
    confirmed_price: float | None
    attribution_tags: tuple[str, ...]
    verified_by_agent: AgentId
    verified_at: datetime


__all__ = [
    "AuthorizedBounds",
    "CallBrief",
    "CallConversationResult",
    "CallOutcomeReport",
    "CallPlanningRequest",
    "CallPlanningResult",
    "CallSpeaker",
    "CallTurn",
    "CallerAction",
    "CallerTurnDecision",
    "ClarificationRequest",
    "ClarificationResult",
    "ClarifyingQuestion",
    "CounterpartyPersona",
    "CounterpartyTurnSignal",
    "CounterpartyVariant",
    "FallbackAction",
    "FallbackDecision",
    "GraphKnownFact",
    "ProviderCandidate",
    "ProviderRankingResult",
    "ProviderReliabilitySignal",
    "RankedProvider",
    "RankingContext",
    "ServiceDiscoveryRequest",
    "ServiceDiscoveryResult",
    "UrgencyLevel",
    "VerificationResult",
    "VerificationVerdict",
    "VerifiedBooking",
]

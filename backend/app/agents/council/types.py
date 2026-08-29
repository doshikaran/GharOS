"""Shared, non-agent-specific dataclasses for the Household Council
(A41-A49, spec §12, §15.9, PHASES.md Phase 12, ADR-019) — E2's
`backend/app/agents/council/`.

Mirrors the role `app.agents.simulator.types` plays for its own package
one phase earlier: one place every A41-A49 module imports the same
request/result shapes from, so the protocol (convene -> each specialist
reports in isolation -> hard constraints eliminate -> each delegate scores
surviving branches -> `council_arbiter.resolve()` -> the Adversary attacks
the resolved option -> the Recorder writes everything) stays legible end
to end.

**The five shapes below the module docstring marker are frozen by this
phase's own brief — exact field names, no deviation.** E4 is coding a
TypeScript mirror against these same names; a field rename here breaks
that contract silently. Every other dataclass in this file (the various
`*Request`/framing shapes) is this package's own implementation detail,
free to evolve, and deliberately kept separate from the frozen five so it
is always obvious which is which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from contracts.graph_types import NodeId, ValuationProfile

from ...solvers.council_arbiter import CouncilResolution

# ---------------------------------------------------------------------------
# Frozen five — do not rename/remove a field without a CTO-adjudicated
# re-freeze (E4 codes a TypeScript mirror against these exact names).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CouncilComposition:
    """A41 Convener's entire output. Deliberately has **no stance/
    reasoning-about-the-decision field of any kind** — A41's own forbidden
    behaviour ("holding a position itself," spec §15.9) is structurally
    impossible to represent here, not merely untested: there is no field
    to smuggle an opinion into, only a participant-selection list."""

    decision_id: NodeId
    question: str
    trigger: str
    convened_specialist_ids: tuple[str, ...]
    """e.g. `("A42", "A43", "A45")` — a subset of `{"A42", ..., "A46"}`."""
    convened_delegate_person_ids: tuple[NodeId, ...]


@dataclass(frozen=True, slots=True)
class SpecialistPosition:
    """A42-A46 specialists' shared output shape. `eliminated_branch_ids`
    is non-empty **only** for a real HARD-severity constraint elimination
    found in that specialist's own scope — Gate 12's "Care's hard
    constraint ELIMINATES options, does not score them down." Every
    concrete specialist module in this package other than
    `care_specialist_agent.py` hardcodes `eliminated_branch_ids=()` in its
    own construction code, never sourced from model output — see each
    module's own docstring for why this is a real, testable guarantee and
    not merely convention."""

    agent_id: str
    stance: Literal["supports", "opposes", "neutral"]
    reasoning: str
    evidence_refs: tuple[str, ...]
    eliminated_branch_ids: tuple[NodeId, ...]


@dataclass(frozen=True, slots=True)
class DelegateScoring:
    """A47 Member Delegate's output for one convened person. `costs` on
    `valuation_profile` is sparse by omission — a branch this person was
    never asked about, or that the elicitation genuinely does not support
    a cost for, is simply absent, never fabricated as `0.0` (A18's own
    established discipline, Phase 8)."""

    person_id: NodeId
    valuation_profile: ValuationProfile
    reasoning: str


@dataclass(frozen=True, slots=True)
class AdversaryAttack:
    """A48 Adversary's entire output — attacks
    `CouncilResolution.winning_branch_id` using real household `OUTCOME`
    history. `cited_outcome_ids` must be non-empty and real — never a
    generic risk template (spec §15.9 A48). **No field exists here for a
    counter-option** — A48's forbidden behaviour ("proposing alternatives
    — that's option generation") is structurally impossible to represent,
    not merely untested."""

    target_branch_id: NodeId
    critique: str
    cited_outcome_ids: tuple[NodeId, ...]


@dataclass(frozen=True, slots=True)
class CouncilBrief:
    """Assembled by plain orchestration code (`pipeline.py`), not a 10th
    agent — spec §15.9 names exactly nine. Deliberately has **no
    verdict/recommendation-override field beyond `resolution` itself**,
    which is deterministic-computed, never LLM-decided — this IS the R4
    "brief only" object (spec §12.2 design rule 5: "the Council never
    makes the final call on R4-tier decisions... humans decide"); nothing
    in this package ever escalates it into an executed action (Gate 12:
    "R4 never auto-resolves — brief only")."""

    decision_id: NodeId
    question: str
    specialist_positions: tuple[SpecialistPosition, ...]
    delegate_scorings: tuple[DelegateScoring, ...]
    adversary_attack: AdversaryAttack
    resolution: CouncilResolution
    risk_register: tuple[str, ...]


# ---------------------------------------------------------------------------
# A41 Convener — request shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HouseholdMemberSummary:
    """One real household member, pre-resolved by the caller (this
    codebase's established "pre-resolved by the caller" precedent — A41
    itself holds no `GraphReader` at all, mirroring A35 Decision Framing's
    identical construction) — real facts a convening decision needs:
    who exists, their role, and (when applicable) a real, caller-supplied
    note on whether/how they are materially affected by *this* decision
    (e.g. "elder with a mobility constraint; this is a car decision")."""

    person_id: NodeId
    display_name: str
    role: str
    """A real `contracts.graph_types.PersonRole` value, e.g. `"adult"`."""
    materially_affected_note: str | None


@dataclass(frozen=True, slots=True)
class ConvenerRequest:
    """A41's entire input for one convening pass."""

    question: str
    trigger: str
    household_members: tuple[HouseholdMemberSummary, ...]


# ---------------------------------------------------------------------------
# A42-A46 specialists — the one shared framing shape every specialist's
# report() method takes, per this phase's Phase-1 isolation requirement:
# "takes only its own scoped data + the decision's basic framing
# (question/trigger/candidate branches) — no parameter through which
# another specialist's or delegate's output could reach it."
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateBranch:
    """One real, concrete option under consideration (a specific car
    listing, a shortlisted property) — the caller-assembled real candidate
    pool, mirroring this codebase's established "no enumerate-all
    primitive, so the caller assembles the pool" precedent
    (`app.agents.simulator.context`'s `resolve_real_anchor_ids`,
    `app.agents.concierge.types.ServiceDiscoveryRequest.known_provider_ids`).
    Council specialists generate no options themselves (spec §12.3 Phase 3
    is a separate, prior step owned by the pipeline's caller, e.g. the
    Simulator's real grounding for a shortlisted property, spec §12.5)."""

    branch_id: NodeId
    label: str
    description: str
    """Real, concrete facts about this one option relevant to specialist
    reasoning — e.g. "2023 Maruti Ertiga, 5-door, door sill height 42cm,
    seat height 51cm, ₹11.2L on-road" — never invented by any specialist;
    this is the caller's own real listing/grounding data."""
    related_node_ids: tuple[NodeId, ...]
    """Real graph node ids that might matter for this specific option
    (e.g. an existing `Obligation` this option would replace, a
    `Constraint` it must satisfy) — each specialist's own
    `ScopedGraphReader` naturally filters these down to only what its
    scope can actually see; an id outside a given specialist's scope
    simply resolves to nothing for that specialist (deny-by-default), so
    handing every specialist the same `related_node_ids` list costs
    nothing and requires no per-specialist filtering by the caller."""


@dataclass(frozen=True, slots=True)
class DecisionFraming:
    """The decision's basic framing — question, trigger, and the real
    candidate branch pool — shared, read-only context every specialist
    receives. Carries no other agent's output of any kind."""

    decision_id: NodeId
    question: str
    trigger: str
    candidate_branches: tuple[CandidateBranch, ...]


@dataclass(frozen=True, slots=True)
class SpecialistReportRequest:
    """A42-A46's entire method input — literally just `framing`. No
    sibling-specialist or delegate data can reach a specialist through
    this shape by construction (Phase-1 isolation, spec §12.3 Phase 1:
    "before seeing any other agent's output")."""

    framing: DecisionFraming


# ---------------------------------------------------------------------------
# A47 Member Delegate — request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DelegateScoringRequest:
    """A47's entire input for one scoring pass. **Deliberately carries no
    `person_id` field** — the concrete `MemberDelegateAgent` instance is
    itself bound to exactly one `person_id` at construction time (spec
    §15.9 A47 forbidden: "speaking for anyone else"), so there is no
    parameter anywhere in this request through which a caller could ask
    one delegate instance to score on behalf of a different person.
    `known_preference_signals` is real, pre-resolved behavioural evidence
    for *that one* bound person (e.g. "historically prioritises boot space
    on family purchases" — drawn from real observed history/interview/
    complaint-inference, per `contracts.graph_types.ValuationProfile.
    elicitation_method`'s own three real sources)."""

    framing: DecisionFraming
    known_preference_signals: tuple[str, ...]
    elicitation_method: Literal["interview", "complaint_inference", "observed_history", "mixed"]


# ---------------------------------------------------------------------------
# A48 Adversary — request shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdversaryAttackRequest:
    """A48's entire input — the arbiter's already-resolved winning branch
    (ADR-019 Decision 7: the Adversary runs *after* `council_arbiter.
    resolve()`, attacking that same winning option, never an earlier
    "leading option" concept and never feeding back into the arbiter's own
    math). `category_tag` is a real `Outcome.attribution_tags`
    decision-category value (ADR-017's own vocabulary, reused unchanged:
    `"relocation"`, `"school_transition"`, `"staff_transition"`,
    `"major_purchase"`), passed straight through to
    `GraphReader.outcome_variance(tag)` — never invented by this module."""

    framing: DecisionFraming
    winning_branch_id: NodeId
    category_tag: str


# ---------------------------------------------------------------------------
# A49 Recorder — request/result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecorderRequest:
    """A49's entire input — every already-produced Council output for one
    decision, exactly as A42-A48 produced it. Nothing here is recomputed,
    reinterpreted, or blended by A49 itself (spec's design rule 2 — A49
    never summarises into consensus)."""

    decision_id: NodeId
    specialist_positions: tuple[SpecialistPosition, ...]
    delegate_scorings: tuple[DelegateScoring, ...]
    adversary_attack: AdversaryAttack
    resolution: CouncilResolution


@dataclass(frozen=True, slots=True)
class RecorderWriteResult:
    """A49's own return value — the real ids of every `CouncilPosition`
    node and `CONCEDED_BY` edge it just wrote, for caller-side
    verification. Carries no content of its own beyond ids: everything
    meaningful was already fully described by `RecorderRequest`'s own
    inputs, never re-derived here."""

    position_ids: tuple[NodeId, ...]
    conceded_by_edge_ids: tuple[str, ...]
    """`contracts.graph_types.EdgeId` values, as plain `str` (matching
    `GraphWriteTool.invoke_idempotent`'s own `write_edge` return shape,
    which hands back the edge id as a plain `str`)."""


__all__ = [
    "AdversaryAttack",
    "AdversaryAttackRequest",
    "CandidateBranch",
    "CouncilBrief",
    "CouncilComposition",
    "ConvenerRequest",
    "DecisionFraming",
    "DelegateScoring",
    "DelegateScoringRequest",
    "HouseholdMemberSummary",
    "RecorderRequest",
    "RecorderWriteResult",
    "SpecialistPosition",
    "SpecialistReportRequest",
]

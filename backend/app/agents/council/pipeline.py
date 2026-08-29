"""Household Council pipeline orchestration (spec §12.3, §15.9, PHASES.md
Phase 12, ADR-019) — E2's `backend/app/agents/council/`.

**Plain code, not a tenth agent.** Spec §15.9 names exactly nine Council
agents (A41-A49); this module calls them in the protocol's own order and
assembles their outputs into a `CouncilBrief` — it holds no reasoning, no
model call, and no aggregation logic of its own beyond tuple-building and
the elimination/survival bookkeeping spec §12.3 Phase 2-4 name explicitly
as the caller's own responsibility, not any one agent's.

## The protocol, exactly as run here (spec §12.3)

1. **Convene** (Phase 0) — A41 selects specialists/delegates and writes
   the real `Decision` node.
2. **Independent reporting** (Phase 1) — every convened specialist's
   `report()` call receives `DecisionFraming` alone, built once, before
   any specialist runs, and never mutated or extended with another
   specialist's output afterward. This is structurally, not just
   behaviourally, isolation: `_convene_and_report` below constructs
   `framing` exactly once and every `report()` call in the loop passes
   that same, already-built object — there is no code path here through
   which specialist `i`'s already-returned `SpecialistPosition` could
   reach specialist `i+1`'s request (see
   `backend/tests/test_council_pipeline.py`'s own AST proof of this
   file's specialist-reporting loop).
3. **Constraint publication / option elimination** (Phase 2) — every
   `HARD`-eliminated branch id any specialist named is collected and
   removed from the surviving-branch set *before* any delegate is asked
   to score anything — delegates are handed a `DecisionFraming` whose
   `candidate_branches` has already dropped every eliminated option, not
   merely an arbiter that later ignores them.
4. **Interest scoring** (Phase 4) — each convened delegate scores only the
   surviving branches.
5. **Mechanism resolution** (Phase 6) — `app.solvers.council_arbiter.
   resolve()` runs as a plain, synchronous function call — **never routed
   through `GeminiClient`** (no `GeminiClient` reference exists anywhere
   near this call in this file).
6. **Adversarial pass** (Phase 5 in spec's prose, run here *after*
   resolution per ADR-019 Decision 7) — A48 attacks
   `resolution.winning_branch_id`.
7. **Record** (Phase 8) — A49 writes everything permanently.
8. **Brief** (Phase 7) — a `CouncilBrief` is assembled and returned; this
   is the R4 "brief only" object (spec §12.2 design rule 5) — nothing in
   this file escalates it into an executed action, and nothing here
   advances `Decision.status` at all (A41's own convening write is the
   only status this package ever sets).

`risk_register` is populated from `AdversaryAttack.critique` alone — the
Adversary is the one designated source of risk-shaped content in this
protocol (spec §12.3 Phase 5/7, §12.4's own worked example is literally
the risk register's content) — never a separately synthesized summary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from contracts.graph_types import NodeId

from ...solvers import council_arbiter
from .adversary_agent import CouncilAdversaryAgent
from .convener_agent import CouncilConvenerAgent
from .errors import MissingParticipantWiring, NoSurvivingBranches
from .member_delegate_agent import MemberDelegateAgent
from .recorder import CouncilRecorderAgent
from .types import (
    AdversaryAttackRequest,
    CandidateBranch,
    ConvenerRequest,
    CouncilBrief,
    DecisionFraming,
    DelegateScoring,
    DelegateScoringRequest,
    RecorderRequest,
    SpecialistPosition,
    SpecialistReportRequest,
)

ElicitationMethod = Literal["interview", "complaint_inference", "observed_history", "mixed"]


class SpecialistAgent(Protocol):
    """Structural shape shared by every A42-A46 concrete specialist class
    (`FinanceSpecialistAgent`, `CareSpecialistAgent`, ...) — they share no
    common base class (each is its own, independently-constructed module
    per ADR-019 Decision 1), so this `Protocol` is what lets this file
    call any of the five through one uniform interface without importing
    all five concrete classes just to type-hint a mapping."""

    def report(self, request: SpecialistReportRequest) -> SpecialistPosition: ...


@dataclass(frozen=True, slots=True)
class CouncilParticipants:
    """Every already-constructed Council agent instance one pipeline run
    needs. Assembling this — real `ScopedGraphReader` wiring per
    specialist, one `MemberDelegateAgent` per potentially-convened person —
    is the caller's own job, never this module's: `pipeline.run` calls
    agents, it does not construct them."""

    convener: CouncilConvenerAgent
    specialists_by_id: Mapping[str, SpecialistAgent]
    """Keyed by the same specialist id strings A41 selects from
    (`"A42"`..`"A46"`) — need not cover all five; only the ones A41 might
    convene for this household."""
    delegates_by_person_id: Mapping[NodeId, MemberDelegateAgent]
    """Keyed by `MemberDelegateAgent.person_id` — need not cover every
    household member; only the ones A41 might convene."""
    adversary: CouncilAdversaryAgent
    recorder: CouncilRecorderAgent


def _collect_eliminated_branch_ids(positions: tuple[SpecialistPosition, ...]) -> tuple[NodeId, ...]:
    """Every real branch id any convened specialist's `HARD` constraint
    eliminated, deduplicated, in first-seen order. Only `care_specialist_
    agent.py` ever populates `eliminated_branch_ids` in this codebase's own
    pipeline today, but this collects from every specialist generically —
    Gate 12's own elimination rule is about *what* eliminates (a real HARD
    constraint), not about hardcoding *which* specialist may."""
    seen: set[NodeId] = set()
    ordered: list[NodeId] = []
    for position in positions:
        for branch_id in position.eliminated_branch_ids:
            if branch_id not in seen:
                seen.add(branch_id)
                ordered.append(branch_id)
    return tuple(ordered)


def run(
    *,
    participants: CouncilParticipants,
    convener_request: ConvenerRequest,
    candidate_branches: tuple[CandidateBranch, ...],
    category_tag: str,
    known_preference_signals_by_person_id: Mapping[NodeId, tuple[str, ...]],
    elicitation_method_by_person_id: Mapping[NodeId, ElicitationMethod],
    cycle_id: str,
) -> CouncilBrief:
    """Runs the full Household Council protocol end to end.

    Args:
        participants: every already-constructed agent instance this run
            may need (see `CouncilParticipants`).
        convener_request: A41's real input (question/trigger/household
            members).
        candidate_branches: the real, caller-assembled candidate pool
            (spec §12.3 Phase 3 — option generation is a separate, prior
            step this pipeline does not perform itself).
        category_tag: the real `Outcome.attribution_tags` category A48
            checks history against.
        known_preference_signals_by_person_id: real, pre-resolved
            behavioural evidence per potentially-convened person. A person
            A41 convenes with no entry here is scored with no known
            signals (an honest, legitimate case — never a wiring error).
        elicitation_method_by_person_id: real elicitation method per
            potentially-convened person. Unlike preference signals, a
            missing entry for a person A41 actually convenes is a real
            caller wiring bug (there is no honest "unknown elicitation
            method" default to fall back to) and raises.
        cycle_id: identifies this whole council run for idempotency across
            every write this protocol performs.

    Returns:
        The finished `CouncilBrief` — an R4 brief only; nothing here
        executes any action or advances `Decision.status`.

    Raises:
        errors.MissingParticipantWiring: A41 convened a specialist id or
            delegate person id `participants` never wired an agent
            instance for, or (for a delegate) `elicitation_method_by_
            person_id` has no entry for a person A41 actually convened.
        errors.NoSurvivingBranches: every real candidate branch was
            eliminated by a HARD constraint before delegate scoring could
            even begin.
        app.solvers.council_arbiter.NoCostSignalError: not a single
            delegate had a real cost for any surviving branch.
        contracts.errors.ToolFailure: any underlying graph write failed.
    """
    composition = participants.convener.convene(convener_request, cycle_id=cycle_id)

    framing = DecisionFraming(
        decision_id=composition.decision_id,
        question=composition.question,
        trigger=composition.trigger,
        candidate_branches=candidate_branches,
    )

    # Phase 1 — independent reporting. `framing` above is built exactly
    # once, before this loop starts, and is never reassigned or extended
    # inside it — every specialist call below receives that same,
    # unchanged object. No specialist's own return value is read back
    # into anything this loop constructs for a later call.
    specialist_positions: list[SpecialistPosition] = []
    for specialist_id in composition.convened_specialist_ids:
        specialist_agent = participants.specialists_by_id.get(specialist_id)
        if specialist_agent is None:
            raise MissingParticipantWiring(kind="specialist id", key=specialist_id)
        position = specialist_agent.report(SpecialistReportRequest(framing=framing))
        specialist_positions.append(position)
    specialist_positions_tuple = tuple(specialist_positions)

    # Phase 2 — constraint publication / option elimination.
    eliminated_branch_ids = _collect_eliminated_branch_ids(specialist_positions_tuple)
    eliminated_set = frozenset(eliminated_branch_ids)
    surviving_branches = tuple(
        branch for branch in candidate_branches if branch.branch_id not in eliminated_set
    )
    surviving_branch_ids = tuple(branch.branch_id for branch in surviving_branches)
    if not surviving_branch_ids:
        raise NoSurvivingBranches(
            decision_id=composition.decision_id, eliminated_branch_ids=eliminated_branch_ids
        )

    surviving_framing = DecisionFraming(
        decision_id=framing.decision_id,
        question=framing.question,
        trigger=framing.trigger,
        candidate_branches=surviving_branches,
    )

    # Phase 4 — interest scoring, surviving branches only.
    delegate_scorings: list[DelegateScoring] = []
    for person_id in composition.convened_delegate_person_ids:
        delegate_agent = participants.delegates_by_person_id.get(person_id)
        if delegate_agent is None or delegate_agent.person_id != person_id:
            raise MissingParticipantWiring(kind="delegate person_id", key=str(person_id))
        elicitation_method = elicitation_method_by_person_id.get(person_id)
        if elicitation_method is None:
            raise MissingParticipantWiring(kind="elicitation_method for person_id", key=str(person_id))
        signals = known_preference_signals_by_person_id.get(person_id, ())
        scoring = delegate_agent.score(
            DelegateScoringRequest(
                framing=surviving_framing,
                known_preference_signals=signals,
                elicitation_method=elicitation_method,
            )
        )
        delegate_scorings.append(scoring)
    delegate_scorings_tuple = tuple(delegate_scorings)

    # Phase 6 — mechanism resolution. Pure function call, no GeminiClient
    # anywhere near it.
    resolution = council_arbiter.resolve(
        surviving_branch_ids=surviving_branch_ids,
        eliminated_branch_ids=eliminated_branch_ids,
        valuation_profiles=tuple(scoring.valuation_profile for scoring in delegate_scorings_tuple),
    )

    # Phase 5 (run here per ADR-019 Decision 7) — adversarial pass against
    # the already-resolved winner.
    adversary_attack = participants.adversary.attack(
        AdversaryAttackRequest(
            framing=framing,
            winning_branch_id=resolution.winning_branch_id,
            category_tag=category_tag,
        )
    )

    # Phase 8 — record everything permanently.
    participants.recorder.record(
        RecorderRequest(
            decision_id=composition.decision_id,
            specialist_positions=specialist_positions_tuple,
            delegate_scorings=delegate_scorings_tuple,
            adversary_attack=adversary_attack,
            resolution=resolution,
        ),
        cycle_id=cycle_id,
    )

    # Phase 7 — brief and escalate. R4: humans decide from here.
    return CouncilBrief(
        decision_id=composition.decision_id,
        question=composition.question,
        specialist_positions=specialist_positions_tuple,
        delegate_scorings=delegate_scorings_tuple,
        adversary_attack=adversary_attack,
        resolution=resolution,
        risk_register=(adversary_attack.critique,),
    )


__all__ = ["CouncilParticipants", "ElicitationMethod", "SpecialistAgent", "run"]

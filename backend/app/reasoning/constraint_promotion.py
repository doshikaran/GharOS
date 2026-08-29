"""Constraint promotion — Memory Consolidation service (spec §20,
PHASES.md Phase 14, ADR-021 Decision 4).

*Not a numbered agent.* Spec §15.9 lists "Memory Consolidation (scheduled
off-peak promotion of observations into consolidated knowledge)" under
"Services (not LLM agents)" — confirmed by grep against the full 69-agent
roster (spec §15 / `gharos-agent-roster` skill): no agent id covers
"constraint promotion." This module is a plain, deterministic sub-service
of that consolidation pipeline, not an ADK agent.

## The job, precisely

Spec §20's own worked example: "repeated dietary mentions -> candidate
hard CONSTRAINT (confirmation-gated)." This module scans a caller-
assembled set of already-extracted `contracts.graph_types.Constraint`
mentions — real graph-resident SOFT constraints, individually written by
whatever perception-layer pipeline (A3/A5/A12/A13) extracted each one from
its own SOURCE_DOCUMENT — for a signal repeated across enough *distinct*
documents to warrant asking a human whether it should become a household-
wide HARD rule. It never itself decides the answer is "yes": its only
output is `ConstraintPromotionCandidate`, a structurally non-authoritative
shape a caller who holds a real confirmation-gate can turn into a real
`contracts.graph_types.ApprovalRequest` (see "Never writes anything"
below).

## Why this is not a duplicate of A16 Constraint Learner

`app.agents.consequence.constraint_learner` (A16) already does something
that sounds similar — "detect repeated signals across multiple
SOURCE_DOCUMENTs that suggest a new, never-explicitly-recorded household
constraint" — but the two operate on genuinely different raw material and
solve genuinely different halves of the problem:

- **A16** reasons over *raw excerpt text* nobody has yet judged to be a
  constraint at all. Because clustering "these five excerpts are plausibly
  the same underlying rule" from free text is itself a judgment call, A16
  needs a real Pro-tier interpretation step per caller-assembled group
  (spec §21.1's cost-discipline table lists exactly this).
- **This module** reasons over *already-extracted, already-normalized*
  `Constraint` nodes — each one already individually judged by an
  upstream extraction agent to be a real (if only individually-sourced,
  SOFT) constraint, with a machine-checkable `structured: dict[str, str]`
  form. Deciding whether two already-normalized structured forms describe
  "the same rule" is expressible as plain equality over already-typed
  data — no natural-language interpretation is left to do, so this module
  makes **no model call at all, not even Flash** (ADR-021 Decision 4
  explicitly permits either choice; this is the "expressible
  deterministically from already-normalized signals" branch, chosen
  because the alternative would spend a second interpretation pass on data
  a human-auditable extraction step already interpreted once). Reusing
  A16's own Pro-tier interpretation for this would launder a second
  hallucination surface onto data that no longer needs one.

## Never writes anything — the safety-critical line

`ConstraintPromotionCandidate.status` is pinned, structurally, to the one
`Literal["pending_confirmation"]` value — there is no code path in this
module (or this dataclass) that can produce a "confirmed" candidate, and
this module holds no `contracts.repositories.GraphWriter` and no
`contracts.arbitration`-style approval-gate import at all: it cannot write
the real, live `contracts.graph_types.Constraint` node under any
circumstance, by construction, not by convention (mirrors A16's own
"no GraphWriter import anywhere" structural guarantee).

Promoting a candidate to a real, authoritative HARD `Constraint` happens
only once a human confirms it through the existing Approval Gate
(`backend/app/arbitration/approval_gate.py`, Phase 5) — this module
produces the structured case for that confirmation
(`ConstraintPromotionCandidate.evidence_bundle`, ready to hand to
`ApprovalGate.request_approval` via an `ArbiterResult` the orchestration
layer assembles) and stops there. The orchestrator (E1's consolidation
service, or E3's dispatch layer) — never this module — holds the
`ApprovalGate` and decides when to actually call `request_approval`.

## Risk tier: R2, not R1, not R3, not R4

`recommended_risk_tier` is always `RiskTier.R2_APPROVE` — resolved via the
real `app.reasoning.risk_policy.classify_risk_tier` table, not hardcoded
independently, so there is exactly one place this classification is
decided. The justification:

- **Why not R1** ("reversible, low-impact, visible" — auto-executed,
  merely notified): `contracts.actions.ArbiterDecision.APPROVE` — the
  decision that actually reaches `ApprovalGate.request_approval` — is
  only ever produced by the Confidence Arbiter for R2/R3
  (`backend/app/arbitration/approval_gate.py`'s own
  `_APPROVAL_TTL_BY_TIER` covers exactly those two tiers). An R1
  classification would resolve to `ArbiterDecision.EXECUTE` and never
  reach a human at all — directly contradicting the safety-critical
  requirement that a promoted constraint is "never yet live/authoritative
  until a human confirms it via the existing Approval Gate flow." R2 is
  therefore the *only* tier among R1/R2 that actually routes through the
  gate this task requires.
- **Why not R3** ("any movement of money"): no money moves as a direct
  effect of confirming a household rule.
- **Why not R4** ("irreversible, high-stakes, emotionally loaded... never
  auto-executed"): R4 does not route to `ApprovalGate.request_approval`
  at all (it routes to `ArbiterDecision.ESCALATE` -> A58 Escalation
  Agent) — again incompatible with "the existing Approval Gate flow."
  Confirming a household rule is also not the class of decision spec
  §18.1 reserves for R4 (relocation, property purchase, care
  arrangements, ending employment, medical choices).
- **Positive case for R2**: this matches `app.reasoning.risk_policy.
  apply_hard_constraint_floor`'s existing, already-tested rule verbatim —
  "hard-constraint involvement forces at least R2" (spec §18.2 rule 2).
  Every candidate this module produces is, by definition, a proposal to
  make something a HARD constraint; the R2 floor that rule already
  encodes for *other* agents' hard-constraint-adjacent actions applies
  here with no exception needed.

## Support threshold

`MIN_CONSTRAINT_PROMOTION_SUPPORT = 3` — one higher than A16's own
`_MIN_SUPPORT_COUNT = 2`. A16's threshold sits under a real Pro-tier
interpretation step that can still say "not actually the same rule" after
seeing the excerpts; this module has no such second check, so before even
proposing a hard-constraint confirmation to a human it requires one more
independent corroborating document. "Distinct source documents," not raw
mention count, exactly mirrors A16/A10's own established support-counting
convention — two mentions inside one document are one occurrence, not two.

## A known, honest limitation

Grouping is exact equality over `(kind, sorted(structured.items()))`.
Near-duplicate normalized values ("nut" vs "nuts", differing
capitalization) will not be merged into the same group. This is a
deliberate choice, not an oversight: canonicalizing `Constraint.structured`
values is the responsibility of whichever upstream extraction agent
populates them; fuzzy-matching structured values *here* would smuggle
back in exactly the kind of NLP judgment this module's whole design
argument (no model call needed) depends on not needing, and a missed
promotion is a far safer failure mode on a hard-constraint path than a
wrongly-merged one (the household re-sees the same reminder either way;
nothing hard-constrains incorrectly).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from .risk_policy import ActionTypes, classify_risk_tier, confidence_floor

MIN_CONSTRAINT_PROMOTION_SUPPORT: int = 3
"""Minimum number of *distinct* SOURCE_DOCUMENTs (via each contributing
Constraint's own provenance) a repeated structured signal must span before
this module even constructs a candidate. See module docstring, "Support
threshold" — one stricter than A16's `_MIN_SUPPORT_COUNT = 2` because this
module's grouping has no Pro-tier double-check behind it."""

_CONFIDENCE_PER_ADDITIONAL_MENTION: float = 0.05
"""How much each source document beyond the threshold adds to
`ConstraintPromotionCandidate.confidence` — see `_promotion_confidence`."""

_CONFIDENCE_CEILING: float = 0.95
"""Never 1.0 — however many corroborating mentions exist, this is still a
candidate awaiting human confirmation, not an established fact (mirrors
`app.reasoning.risk_policy`'s own R4 floor of 0.92, chosen for the same
reason: "never silently proceed" applies to how much certainty is
*claimed*, not only to whether an action executes)."""


def _promotion_confidence(support_count: int) -> float:
    """`confidence_floor(RiskTier.R2_APPROVE)` (0.75) at exactly the
    threshold, +0.05 per additional distinct corroborating source document
    beyond the threshold, capped at `_CONFIDENCE_CEILING`.

    Anchoring the base to the real R2 confidence floor (rather than an
    independently-chosen constant) means a threshold-clearing candidate is
    computed to sit right at the bar `ConfidenceArbiter` would require for
    R2 in the first place — deliberately not comfortably above it, since
    3 corroborating mentions with no further interpretation is exactly a
    borderline-adequate case, not a strong one.

    Worked example: `support_count=3` (at threshold) -> 0.75. `support_
    count=5` -> 0.75 + 0.05*2 = 0.85. `support_count=9` or more -> capped
    at 0.95 (0.75 + 0.05*6 = 1.05, capped).
    """
    base = confidence_floor(RiskTier.R2_APPROVE)
    extra = _CONFIDENCE_PER_ADDITIONAL_MENTION * (support_count - MIN_CONSTRAINT_PROMOTION_SUPPORT)
    return min(_CONFIDENCE_CEILING, base + extra)


@dataclass(frozen=True, slots=True)
class ConstraintMention:
    """One already-written, real `contracts.graph_types.Constraint` node,
    reduced to the fields this module reasons over. Assembled by the
    caller (the consolidation orchestrator) — this module has no
    `GraphReader` of its own and performs no graph enumeration, matching
    `app.agents.consequence.types.HouseholdContext`'s own documented
    reason: `contracts.repositories.GraphReader` has no "list every node
    of type X" primitive to build this pool from directly.

    `source_document_id` is required, not optional: a mention this module
    cannot attribute to a specific SOURCE_DOCUMENT cannot contribute
    supporting evidence toward promoting a hard constraint (mirrors A12's
    "uncitable -> discarded" discipline, spec §7.6) — such a mention is
    simply not passed to `scan_for_constraint_promotions` at all.
    """

    constraint_id: NodeId
    kind: ConstraintKind
    severity: ConstraintSeverity
    """Only `ConstraintSeverity.SOFT` mentions are eligible for promotion
    consideration (see `scan_for_constraint_promotions`) — a mention
    already `HARD` is already live and authoritative; it needs no
    promotion."""
    structured: dict[str, str]
    original_text: str
    source_document_id: NodeId


@dataclass(frozen=True, slots=True)
class ConstraintPromotionCandidate:
    """A detected repeated signal proposing a new household-wide HARD
    constraint. **Never a real `contracts.graph_types.Constraint` node —**
    `status` only ever takes the one value below, structurally (see module
    docstring, "Never writes anything"). `kind`/`structured`/
    `original_text`/`severity` mirror `Constraint`'s own field shape
    exactly (same names, same types) so a caller building the eventual
    real `Constraint` node, once a human confirms, can do so by copying
    these fields verbatim plus a fresh `id`/`Provenance` — never by
    re-deriving or re-summarizing them.
    """

    pending_id: str
    kind: ConstraintKind
    structured: dict[str, str]
    original_text: str
    """Every distinct contributing mention's own original text, joined
    (order-preserving, deduplicated) with `"; "` — never discarded, never
    collapsed to just one example (`Constraint.original_text`'s own "never
    discarded" provenance rule, spec §14.3 rule 5, applied to the full set
    of evidence a promotion candidate rests on, not just its first
    mention)."""
    support_count: int
    contributing_constraint_ids: tuple[NodeId, ...]
    contributing_source_document_ids: tuple[NodeId, ...]
    confidence: float
    recommended_risk_tier: RiskTier
    evidence_bundle: EvidenceBundle
    """Ready to hand to `backend/app/arbitration/approval_gate.py`'s
    `ApprovalGate.request_approval` via an `ArbiterResult` the
    orchestration layer assembles — this module does not construct that
    `ArbiterResult` itself (it would require importing arbitration-layer
    types this module has no need of and holding no approval-gate
    capability of its own, per the E2 charter's "reasoning agents never
    hold action credentials")."""
    severity: ConstraintSeverity = ConstraintSeverity.HARD
    """Always HARD — spec §20's own wording is "candidate hard
    CONSTRAINT," not "candidate constraint matching the input mentions'
    severity." A repeated signal that only ever warranted a soft
    preference does not need this promotion path at all."""
    status: Literal["pending_confirmation"] = "pending_confirmation"


def _signature(mention: ConstraintMention) -> tuple[ConstraintKind, tuple[tuple[str, str], ...]]:
    """The exact-equality grouping key — see module docstring's "known,
    honest limitation" for why this is exact equality, not fuzzy matching.
    """
    return (mention.kind, tuple(sorted(mention.structured.items())))


def _evaluate_group(mentions: tuple[ConstraintMention, ...]) -> ConstraintPromotionCandidate | None:
    """Builds a candidate for one already-grouped (same signature) set of
    mentions, or returns `None` if their distinct-source-document support
    does not clear `MIN_CONSTRAINT_PROMOTION_SUPPORT`."""
    distinct_source_ids = tuple(sorted({mention.source_document_id for mention in mentions}))
    support_count = len(distinct_source_ids)
    if support_count < MIN_CONSTRAINT_PROMOTION_SUPPORT:
        return None

    first = mentions[0]
    original_text = "; ".join(dict.fromkeys(mention.original_text for mention in mentions))
    confidence = _promotion_confidence(support_count)
    recommended_risk_tier = classify_risk_tier(ActionTypes.CONFIRM_CONSTRAINT_PROMOTION)

    evidence_bundle = EvidenceBundle(
        proposed_action=(
            f"Promote repeated {first.kind.value} signal to a household-wide hard constraint: "
            f"{first.structured}"
        ),
        reasoning=(
            f"{support_count} distinct source documents independently describe the same "
            f"{first.kind.value} rule ({first.structured}), meeting the promotion threshold of "
            f"{MIN_CONSTRAINT_PROMOTION_SUPPORT}. Support is counted deterministically over "
            "already-normalized structured signals — each contributing mention's structured "
            "form was interpreted once already, at extraction time, and is not re-interpreted "
            "here."
        ),
        evidence_consulted=tuple(str(source_id) for source_id in distinct_source_ids),
        confidence=confidence,
        consequence_if_wrong=(
            "If wrongly promoted: household agents begin treating this as a non-negotiable "
            "hard rule (e.g. eliminating menu or scheduling options outright) until a human "
            "corrects it via supersession. If wrongly withheld: the household keeps "
            "re-encountering the same unrecorded rule as separate, individually low-authority "
            "mentions instead of one stable, enforced constraint."
        ),
    )

    return ConstraintPromotionCandidate(
        pending_id=f"pending-constraint-promotion:{uuid.uuid4().hex}",
        kind=first.kind,
        structured=dict(first.structured),
        original_text=original_text,
        support_count=support_count,
        contributing_constraint_ids=tuple(sorted({mention.constraint_id for mention in mentions})),
        contributing_source_document_ids=distinct_source_ids,
        confidence=confidence,
        recommended_risk_tier=recommended_risk_tier,
        evidence_bundle=evidence_bundle,
    )


def scan_for_constraint_promotions(
    mentions: tuple[ConstraintMention, ...],
) -> tuple[ConstraintPromotionCandidate, ...]:
    """Groups `mentions` by exact `(kind, structured)` signature and
    returns one `ConstraintPromotionCandidate` per group whose distinct-
    source-document support clears `MIN_CONSTRAINT_PROMOTION_SUPPORT`.

    Args:
        mentions: already-written `Constraint` nodes, reduced to
            `ConstraintMention`, assembled by the caller (see
            `ConstraintMention`'s docstring for why this module does not
            assemble the pool itself). Mentions whose `severity` is
            already `ConstraintSeverity.HARD` are ignored — already-live,
            already-authoritative constraints need no promotion.

    Returns:
        Zero or more candidates, one per genuinely-repeated signal that
        cleared the threshold. Never includes a below-threshold group —
        proven by `test_constraint_promotion.py`'s
        `test_below_threshold_produces_no_candidate`.
    """
    eligible = tuple(mention for mention in mentions if mention.severity is ConstraintSeverity.SOFT)

    groups: dict[tuple[ConstraintKind, tuple[tuple[str, str], ...]], list[ConstraintMention]] = {}
    for mention in eligible:
        groups.setdefault(_signature(mention), []).append(mention)

    candidates: list[ConstraintPromotionCandidate] = []
    for group_mentions in groups.values():
        candidate = _evaluate_group(tuple(group_mentions))
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


__all__ = [
    "MIN_CONSTRAINT_PROMOTION_SUPPORT",
    "ConstraintMention",
    "ConstraintPromotionCandidate",
    "scan_for_constraint_promotions",
]

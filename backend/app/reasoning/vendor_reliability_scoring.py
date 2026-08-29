"""Vendor reliability scoring — Memory Consolidation service (spec §20,
PHASES.md Phase 14, ADR-021 Decision 5).

*Not a numbered agent* — same status as `constraint_promotion.py`
alongside it (spec §15.9, "Services (not LLM agents)"). A pure,
deterministic formula over already-structured signals — the same class of
decision as `docs/FAIRNESS_GUARANTEE.md`'s EF1 solver and ADR-019's
minimax-regret arbiter: **no model call anywhere in this module**, not
even Flash. There is no natural-language judgment left to make once the
inputs are `Outcome.attribution_tags` (a closed, four-value vocabulary,
ADR-016) and plain hour counts — this is arithmetic.

## Input signal — the real, documented vocabulary (ADR-016)

`Outcome.attribution_tags` gets a defined vocabulary for provider/vendor-
reliability signals: `"no_show"`, `"on_time"`, `"rescheduled"`,
`"unresponsive_to_automated_caller"`. This module's `_TAG_WEIGHTS` table
is the only place those four strings are interpreted numerically — no
other tag value in `attribution_tags` affects the score (an outcome
tagged, say, `"price_change"` from the Ledger domain is silently not
counted here; it is simply not part of this vocabulary).

## A known, honest graph-model gap (named, not papered over)

Checked directly before writing this module: `contracts.graph_types.
EdgeType`'s frozen table has **no edge connecting OUTCOME to VENDOR**.
`COMPLETES_INTO` is `OBLIGATION -> OUTCOME`; the only edge naming `VENDOR`
at all is `OWED_TO` (`LEDGER_EVENT -> VENDOR | PERSON`). ADR-016's
attribution-tag vocabulary was introduced for **PROVIDER** reliability
(`BOOKED_WITH`: `OBLIGATION -> PROVIDER`, then that obligation's own
`COMPLETES_INTO` `Outcome`) — `backend/app/adapters/vendor_relations.py`
(A33, E3, Phase 7) independently documents this exact same gap for
`VENDOR` in its own module docstring ("A known, honest graph-model gap"):
there is genuinely no first-class graph path from a `Vendor` to its own
`Outcome` history yet.

This module does not invent a new `EdgeType` (contracts are CTO-owned,
PHASES.md Appendix D rule 4) and does not silently assume one exists. It
takes `recent_outcomes: tuple[Outcome, ...]` as a caller-assembled
parameter — exactly A33's own established precedent for `VendorRequest
Observation` ("supplied by the caller... this module has no live channel
of its own that observes a vendor interaction, and does not pretend to").
How the caller determines which `Outcome`s belong to which `Vendor`
(today: almost certainly a `Provider`-shaped booking whose counterparty
happens to also be tracked as this household's `Vendor` for recurring-
commitment purposes; going forward: a real `VENDOR <-> OUTCOME` edge type,
raised to the CTO as a follow-up ADR the same way A33 already raised it)
is the orchestrator's problem, not this module's.

## Relationship to `app.adapters.vendor_relations` (A33, E3, Phase 7)

A33 already computes and writes `Vendor.reliability_score` /
`response_latency_hours` from a *different* signal — raw observed
request/response/completion timestamps (`VendorRequestObservation`). This
module computes the *same two fields* from a different, complementary
signal: `Outcome.attribution_tags` set by whatever process (most likely,
today, an Outbound Concierge call outcome) tags an interaction after the
fact. Both are legitimate, real signals; this module does not replace or
call into A33's code (out of E2's ownership — `backend/app/adapters/` is
E3's), and does not attempt to reconcile the two write paths itself. This
is flagged explicitly in this phase's report as a real integration
question for E1/E3's orchestrator to resolve (e.g. run one as the nightly
consolidation baseline with the other layered on top as live per-
interaction updates) — a call this module cannot correctly make on its
own without visibility into how the orchestrator sequences both passes.

## The formula, worked example included (hand-verifiable)

Two components, combined:

**1. Tag-rate component** (`_tag_rate_score`) — the dominant signal
(weight 0.7), because ADR-016's vocabulary is the more direct evidence of
whether the vendor actually delivered:

    _TAG_WEIGHTS = {"on_time": +1.0, "rescheduled": +0.5,
                    "no_show": -1.0, "unresponsive_to_automated_caller": -1.0}

    rate_raw   = sum(_TAG_WEIGHTS[tag] for every occurrence of a
                 vocabulary tag across every outcome's attribution_tags)
                 / (count of those occurrences)
    rate_score = (rate_raw + 1) / 2        # rescale [-1, 1] -> [0, 1]

`rescheduled` gets partial (+0.5, not 0 and not -1): the vendor did
engage, the plan merely slipped — worse than `on_time`, better than a
`no_show`. `unresponsive_to_automated_caller` is weighted equal to
`no_show` (-1.0): refusing to engage with automated outreach at all is at
least as bad a reliability signal as showing up late/not at all for a
scheduled interaction, for this household's purposes.

**2. Latency component** (`_latency_score`) — weight 0.3, a softer,
secondary signal (a slow-but-eventually-reliable vendor is still usable):

    updated_latency = new observations' mean hours, blended 40/60 with
                       the vendor's prior stored `response_latency_hours`
                       if one exists (recency-weighted: one scoring pass
                       should meaningfully move the trend without letting
                       a single noisy batch overwrite it outright), or
                       carried forward unchanged if no new observations
                       arrived this run, or `None` if there has never
                       been any latency data at all (in which case the
                       latency component is dropped and the final score
                       is `rate_score` alone — never a fabricated 0.0 or
                       1.0 standing in for "no data," matching A33's own
                       "`None` is honest; a placeholder number is not"
                       precedent).
    latency_score   = clamp(1 - updated_latency / 48.0, 0.0, 1.0)

48 hours (2 days) is the chosen ceiling: a household vendor (plumber,
society office, school admin) who takes two full days just to *respond*
(not complete the work — respond) scores zero on this component; the
scale is linear between "instant" (score 1.0) and that ceiling.

**Final:** `reliability_score = 0.7 * rate_score + 0.3 * latency_score`
(or `rate_score` alone if `updated_latency is None`).

### Worked example (reproduced exactly in
`backend/tests/test_vendor_reliability_scoring.py::
test_worked_example_matches_module_docstring`)

Four outcomes tagged `on_time`, `on_time`, `no_show`, `rescheduled`; no
prior latency on file; three new latency observations of 8.0, 12.0, 16.0
hours.

    rate_raw       = (1.0 + 1.0 - 1.0 + 0.5) / 4      = 1.5 / 4   = 0.375
    rate_score     = (0.375 + 1) / 2                              = 0.6875
    updated_latency = mean(8.0, 12.0, 16.0)             = 12.0  (no prior -> unblended)
    latency_score  = 1 - 12.0 / 48.0                              = 0.75
    reliability_score = 0.7 * 0.6875 + 0.3 * 0.75
                       = 0.48125 + 0.225                          = 0.70625
    confidence     = min(1.0, 4 informative tags / 5.0)           = 0.8

Every number above is an exact terminating decimal in ordinary decimal
arithmetic — checkable by hand, digit by digit, with no rounding built
into the formula at any intermediate step. (The test that reproduces this
example compares the final `0.7*0.6875 + 0.3*0.75` product with
`pytest.approx`, not `==` — IEEE-754 binary floating point represents
0.70625 as `0.7062499999999999`; that is a float-representation artifact
of Python's `float` type, not a rounding step this module's formula
introduces.)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import structlog
from contracts.graph_types import AgentId, Derivation, Outcome, Provenance, Vendor
from contracts.repositories import GraphWriter

logger = structlog.get_logger(__name__)

_DERIVING_AGENT = AgentId("memory-consolidation-vendor-scoring")
"""Not an `"A<N>"` roster id — this is a Memory Consolidation *service*
(spec §15.9), not one of the 69 numbered agents. `AgentId` is a plain
`NewType(str)` (contracts/graph_types.py), not an enum restricted to the
roster, so a clearly non-numeric, descriptive value is both valid and
greppable without falsely implying roster membership."""

_TAG_WEIGHTS: dict[str, float] = {
    "on_time": 1.0,
    "rescheduled": 0.5,
    "no_show": -1.0,
    "unresponsive_to_automated_caller": -1.0,
}
"""ADR-016's closed attribution-tag vocabulary, and only that vocabulary —
any other tag value present in `Outcome.attribution_tags` is ignored by
this module (not an error; plenty of legitimate tags exist for other
subsystems' purposes, e.g. Ledger-domain tags)."""

_RATE_WEIGHT = 0.7
_LATENCY_WEIGHT = 0.3
_LATENCY_CEILING_HOURS = 48.0
_LATENCY_RECENCY_WEIGHT = 0.4
"""Blend weight for new latency observations against the vendor's prior
stored value — see module docstring, "Latency component"."""
_FULL_CONFIDENCE_TAG_COUNT = 5.0
"""Number of informative tag occurrences at which this module treats its
own `confidence` as fully 1.0 — mirrors `app.adapters.vendor_relations.
_RELIABILITY_CONFIDENCE_SAMPLE_SIZE`'s identical precedent and value
exactly, for the same reason: a score computed from one tag is honestly
less trustworthy than one computed from five."""


def _tag_rate_score(outcomes: tuple[Outcome, ...]) -> tuple[float, int] | None:
    """Returns `(rate_score in [0, 1], informative_tag_occurrence_count)`,
    or `None` if no outcome carries any tag from `_TAG_WEIGHTS` at all
    (nothing to compute — never a fabricated neutral 0.5)."""
    weighted_sum = 0.0
    count = 0
    for outcome in outcomes:
        for tag in outcome.attribution_tags:
            weight = _TAG_WEIGHTS.get(tag)
            if weight is None:
                continue
            weighted_sum += weight
            count += 1
    if count == 0:
        return None
    rate_raw = weighted_sum / count
    rate_score = (rate_raw + 1.0) / 2.0
    return rate_score, count


def _updated_latency_hours(
    previous_latency_hours: float | None,
    new_latency_observations_hours: tuple[float, ...],
) -> float | None:
    """`previous_latency_hours` carried forward unchanged if there are no
    new observations this run; a recency-weighted blend of the two if
    both exist; the new observations' plain mean if there was no prior
    value at all; `None` only if neither has ever existed."""
    if not new_latency_observations_hours:
        return previous_latency_hours
    new_mean = sum(new_latency_observations_hours) / len(new_latency_observations_hours)
    if previous_latency_hours is None:
        return new_mean
    return _LATENCY_RECENCY_WEIGHT * new_mean + (1.0 - _LATENCY_RECENCY_WEIGHT) * previous_latency_hours


def _latency_score(latency_hours: float) -> float:
    return max(0.0, min(1.0, 1.0 - latency_hours / _LATENCY_CEILING_HOURS))


@dataclass(frozen=True, slots=True)
class VendorReliabilityUpdate:
    """Everything computed for one vendor's scoring pass — every
    intermediate component is kept, not just the final score, so a caller
    (or a CTO gate review) can hand-verify the arithmetic without
    recomputing it."""

    new_reliability_score: float
    new_response_latency_hours: float | None
    rate_score: float
    latency_score: float | None
    informative_tag_count: int
    confidence: float


def compute_vendor_reliability_update(
    *,
    vendor: Vendor,
    recent_outcomes: tuple[Outcome, ...],
    new_latency_observations_hours: tuple[float, ...] = (),
) -> VendorReliabilityUpdate | None:
    """Pure computation — no graph access, no write. See module docstring
    for the full formula and a worked example.

    Args:
        vendor: the vendor's current node (for its prior
            `response_latency_hours` only — this function does not read
            `vendor.reliability_score` at all, since the new score is
            always fully recomputed from `recent_outcomes`, never
            incrementally adjusted).
        recent_outcomes: `Outcome`s the caller has already determined
            pertain to this vendor (see module docstring, "A known,
            honest graph-model gap").
        new_latency_observations_hours: raw hours-to-first-response
            observations gathered since the vendor's `response_latency_
            hours` was last updated (caller-assembled, same precedent as
            `app.adapters.vendor_relations.VendorRequestObservation`).

    Returns:
        `None` if `recent_outcomes` carries no ADR-016-vocabulary tag at
        all (nothing to compute from — never a fabricated neutral score).
        Otherwise a `VendorReliabilityUpdate` with every component filled
        in.
    """
    tag_result = _tag_rate_score(recent_outcomes)
    if tag_result is None:
        return None
    rate_score, tag_count = tag_result

    updated_latency = _updated_latency_hours(vendor.response_latency_hours, new_latency_observations_hours)
    if updated_latency is None:
        latency_score: float | None = None
        new_score = rate_score
    else:
        latency_score = _latency_score(updated_latency)
        new_score = _RATE_WEIGHT * rate_score + _LATENCY_WEIGHT * latency_score

    confidence = min(1.0, tag_count / _FULL_CONFIDENCE_TAG_COUNT)

    return VendorReliabilityUpdate(
        new_reliability_score=new_score,
        new_response_latency_hours=updated_latency,
        rate_score=rate_score,
        latency_score=latency_score,
        informative_tag_count=tag_count,
        confidence=confidence,
    )


class VendorAttributionReliabilityScorer:
    """The deterministic T3 write half — holds a real `GraphWriter`
    directly, mirroring `app.agents.consequence.obligation_writer.
    ObligationWriter` (A15) and `app.agents.consequence.
    obligation_writer`'s own established E2 precedent for a deterministic
    writer holding `contracts.repositories.GraphWriter` directly, with no
    T3 tool wrapper needed (this is an internal graph write — R0 "graph_
    maintenance" per `app.reasoning.risk_policy` — not an approval-gated
    external action, so no `ApprovalGatedTool` import belongs here and
    none exists)."""

    def __init__(self, *, graph_writer: GraphWriter) -> None:
        self._graph_writer = graph_writer

    def score_and_write(
        self,
        *,
        vendor: Vendor,
        recent_outcomes: tuple[Outcome, ...],
        new_latency_observations_hours: tuple[float, ...] = (),
        as_of: datetime | None = None,
    ) -> Vendor | None:
        """Computes `compute_vendor_reliability_update` and, if it
        produces a genuinely new value, supersedes `vendor` with the
        updated version via `GraphWriter.supersede_node`.

        Returns:
            The new `Vendor` version if a write occurred; `None` if there
            was nothing to compute (`recent_outcomes` carried no
            ADR-016-vocabulary tag) or the computed score/latency are
            unchanged from `vendor`'s current values (no-op, no write
            attempted — mirrors A33's identical no-op precedent).
        """
        current_time = as_of if as_of is not None else datetime.now(UTC)
        update = compute_vendor_reliability_update(
            vendor=vendor,
            recent_outcomes=recent_outcomes,
            new_latency_observations_hours=new_latency_observations_hours,
        )
        if update is None:
            return None
        if (
            update.new_reliability_score == vendor.reliability_score
            and update.new_response_latency_hours == vendor.response_latency_hours
        ):
            return None

        updated_vendor = replace(
            vendor,
            reliability_score=update.new_reliability_score,
            response_latency_hours=update.new_response_latency_hours,
            provenance=Provenance(
                # AMBIGUOUS, never INFERRED: this is an aggregate over
                # possibly many outcomes, each with its own (possibly
                # different) originating source — no single source_ref
                # applies, mirroring A33's identical reasoning and
                # `Provenance.__post_init__`'s own requirement that
                # INFERRED always carries a source_ref.
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=update.confidence,
                deriving_agent=_DERIVING_AGENT,
                created_at=current_time,
            ),
        )
        self._graph_writer.supersede_node(vendor.id, updated_vendor)
        logger.info(
            "reasoning.vendor_reliability_scoring.updated",
            vendor_id=str(vendor.id),
            reliability_score=update.new_reliability_score,
            response_latency_hours=update.new_response_latency_hours,
            informative_tag_count=update.informative_tag_count,
            confidence=update.confidence,
        )
        return updated_vendor


__all__ = [
    "VendorAttributionReliabilityScorer",
    "VendorReliabilityUpdate",
    "compute_vendor_reliability_update",
]

"""Deterministic multi-factor provider scoring for A52 (spec §13.2 Step
3, §15.10, PHASES.md Phase 10) — E2's half of
`backend/app/agents/concierge/`.

Mirrors this codebase's established "external checkable signal, never
LLM self-critique" split (`app.solvers.fair_allocation.verify_ef1` for
A19, `app.agents.intention_action.schedule_parsing.
person_availability_for_window` for A25): the actual rank order and every
per-provider reason come entirely from this pure, no-model-call module.
`provider_ranking_agent.ProviderRankingAgent` calls a Pro-tier model only
to write a natural-language narrative gloss *on top of* this already-
final order — never to decide it (Gate 10: "ranking explainable -> the
user sees why #1 is #1"; spec §15.10 A52 forbidden list: "opaque
ranking"). Every function here is plain arithmetic over real inputs, unit
-testable with zero Gemini mocking.
"""

from __future__ import annotations

from .types import ProviderCandidate, RankedProvider, RankingContext, UrgencyLevel

_ROUTINE_WEIGHTS: dict[str, float] = {
    "rating": 0.40,
    "distance": 0.20,
    "availability": 0.15,
    "price": 0.10,
    "reliability": 0.15,
}
_ELEVATED_WEIGHTS: dict[str, float] = {
    "rating": 0.10,
    "distance": 0.15,
    "availability": 0.55,
    "price": 0.05,
    "reliability": 0.15,
}
"""Two named weight profiles, each summing to `1.0`. Spec §13.2 Step 1:
"if pain is reported -> urgency escalates -> the search prioritises
earliest availability over rating" — made concrete as a real reweighting
(availability's share rises from 0.15 to 0.55, rating's falls from 0.40
to 0.10) rather than a vague "consider urgency" instruction to a model.

Insurance acceptance is deliberately NOT a ranking factor here: spec
§13.4's feature list names "insurance/coverage filtering" as a discovery-
stage feature (E3's A51 job — candidates that don't accept the
household's insurer are filtered out before A52 ever sees them), and
`ProviderCandidate` carries no structured insurance-acceptance field to
score against (only free-text `specialisations`) — scoring against that
would mean guessing at an insurer match from unstructured text, exactly
the kind of guess this deterministic module is built to avoid."""

_NO_SHOW_PENALTY = 0.5
"""A flat penalty subtracted from a provider's total score whenever
`ProviderReliabilitySignal.no_show_count > 0` — large enough (weighted
component scores are bounded to `[0.0, 1.0]`, weights sum to `1.0`, so an
un-penalised total score is itself bounded to roughly `[0.0, 1.0]`) that
a real no-show history reliably demotes a provider even against an
otherwise-highest-scoring candidate (Gate 10's own literal test case:
"a provider who no-showed before is demoted"), rather than a soft nudge
that a strong rating/distance/availability combination could out-weigh."""


def _rating_component(candidate: ProviderCandidate) -> float:
    if candidate.rating is None:
        return 0.5  # no evidence either way — never penalised for missing data
    return max(0.0, min(1.0, candidate.rating / 5.0))


def _distance_component(candidate: ProviderCandidate) -> float:
    if candidate.distance_km is None:
        return 0.5
    return 1.0 / (1.0 + max(0.0, candidate.distance_km))


def _availability_component(candidate: ProviderCandidate, context: RankingContext) -> float:
    offset_days = context.provider_earliest_offset_days.get(candidate.provider_id)
    if offset_days is None:
        return 0.5  # unresolved — never treated as "unavailable"
    return 1.0 / (1.0 + max(0.0, offset_days))


_PRICE_BAND_SCORES: dict[str, float] = {"$": 1.0, "$$": 0.66, "$$$": 0.33, "$$$$": 0.0}


def _price_component(candidate: ProviderCandidate) -> float:
    if candidate.price_band is None:
        return 0.5
    return _PRICE_BAND_SCORES.get(candidate.price_band, 0.5)


def _reliability_component(
    candidate: ProviderCandidate, context: RankingContext
) -> tuple[float, bool, str | None]:
    """Returns `(component_score, demoted, reason)`. A provider with no
    prior-experience signal at all (new discovery, or an existing
    provider with no completed-obligation `Outcome` history yet) scores
    neutrally — never penalised for lacking history."""
    if not candidate.is_existing_household_provider:
        return 0.5, False, None
    signal = context.reliability_by_provider.get(candidate.provider_id)
    if signal is None or signal.total_outcomes_considered == 0:
        return 0.5, False, None

    demoted = signal.no_show_count > 0
    base = signal.on_time_count / signal.total_outcomes_considered

    if demoted:
        reason = (
            f"prior household experience: {signal.no_show_count} no-show(s) out of "
            f"{signal.total_outcomes_considered} recorded visit(s) — demoted"
        )
    elif signal.on_time_count > 0:
        reason = (
            f"prior household experience: {signal.on_time_count} on-time visit(s) out of "
            f"{signal.total_outcomes_considered} recorded"
        )
    else:
        reason = None
    return base, demoted, reason


def score_candidate(
    candidate: ProviderCandidate, context: RankingContext
) -> tuple[float, dict[str, float], bool, tuple[str, ...]]:
    """Scores one candidate. Returns `(total_score, score_components,
    demoted_for_reliability, reasons)` — `reasons` is always real and
    specific (grounded in the actual numbers used), never generic."""
    weights = _ELEVATED_WEIGHTS if context.urgency is UrgencyLevel.ELEVATED else _ROUTINE_WEIGHTS

    components = {
        "rating": _rating_component(candidate),
        "distance": _distance_component(candidate),
        "availability": _availability_component(candidate, context),
        "price": _price_component(candidate),
    }
    reliability_score, demoted, reliability_reason = _reliability_component(candidate, context)
    components["reliability"] = reliability_score

    total = sum(weights[key] * components[key] for key in weights)
    if demoted:
        total -= _NO_SHOW_PENALTY

    reasons: list[str] = []
    if candidate.rating is not None:
        reasons.append(f"rated {candidate.rating:.1f}/5")
    if candidate.distance_km is not None:
        reasons.append(f"{candidate.distance_km:.1f} km away")
    offset_days = context.provider_earliest_offset_days.get(candidate.provider_id)
    if offset_days is not None:
        reasons.append(f"earliest availability in {offset_days:.0f} day(s)")
    if candidate.price_band is not None:
        reasons.append(f"price band {candidate.price_band}")
    if reliability_reason is not None:
        reasons.append(reliability_reason)
    if not reasons:
        reasons.append(f"the only real candidate found for {candidate.category}")

    return total, components, demoted, tuple(reasons)


def rank_candidates(
    candidates: tuple[ProviderCandidate, ...], context: RankingContext
) -> tuple[RankedProvider, ...]:
    """Ranks every candidate, highest score first. Stable on ties
    (`list.sort` — Python's sort is stable, so equal-scoring candidates
    keep their original relative order rather than an arbitrary one).

    Args:
        candidates: every real `ProviderCandidate` to rank (E3's A51
            output).
        context: real, caller-resolved scoring context (see
            `types.RankingContext`).

    Returns:
        `RankedProvider` entries, `rank=1` first, each carrying its own
        real `reasons` and full `score_components` breakdown — never an
        opaque score with no stated reason.
    """
    scored = [(candidate, *score_candidate(candidate, context)) for candidate in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)

    return tuple(
        RankedProvider(
            provider_id=candidate.provider_id,
            name=candidate.name,
            rank=index,
            score=total,
            reasons=reasons,
            demoted_for_reliability=demoted,
            score_components=components,
        )
        for index, (candidate, total, components, demoted, reasons) in enumerate(scored, start=1)
    )


__all__ = ["rank_candidates", "score_candidate"]

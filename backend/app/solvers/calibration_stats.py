"""Deterministic calibration/variance statistics for the Household
Simulator's Calibration agent (PHASES.md Phase 11, E1 work item — "OUTCOME
variance queries"; spec §11.5/§16.2: "Calibration/variance calculator —
this household's own OUTCOME variance ... thin history -> the calling
agent must say so, never fabricate false precision"; ADR-017).

**No LLM call anywhere in this module.** A39 (Calibration, E2) supplies a
decision category (`Outcome.attribution_tags` value, e.g. `"relocation"`)
and the real `Outcome` nodes `GraphReader.outcome_variance(tag)` returns
for it; turning that tuple into a mean/stdev/confidence-band figure is
pure arithmetic and belongs in code, exactly like `salary_calculator.py`
(Phase 7) and `fair_allocation.py` (Phase 8) — an agent never computes
statistics itself. This module does no graph I/O (mirrors both those
modules' own "pure function over plain data" pattern): the caller (A39)
fetches the `Outcome` tuple via `GraphReader` and hands it in directly.

## The thin-history threshold — not a new arbitrary number

`MIN_SAMPLE_SIZE_FOR_CALIBRATION = 3` is the same threshold precedent as
Phase 9's Slippage Analyst (`test_slippage_analyst_agent.py`: "Exactly N=3
attempts triggers escalation"), reused here rather than inventing a second
magic number for a structurally identical judgment call: below this many
real samples, a numeric confidence figure is manufactured precision, not
evidence. Spec §11.5 names this failure mode explicitly ("Cold start ...
be honest") — `CalibrationEstimate.is_thin_history` makes it a
distinguishable, checkable field on the output, never a silent guess.

## Sample size counts *resolved* outcomes only

`Outcome.variance` is `float | None` — an `Outcome` node can exist for a
prediction whose real-world result has not yet been observed/scored
(`actual`/`variance` not yet settled). Such an entry carries no variance
evidence to calibrate against, so `compute_calibration`'s `sample_size` —
and every statistic derived from it — counts only outcomes whose
`variance` is not `None`. An outcome with `variance=None` is silently
excluded from the count and the arithmetic, never treated as a zero.

## Thin-history output shape (frozen, per this phase's brief)

When `is_thin_history` is `True` (`sample_size < MIN_SAMPLE_SIZE_FOR_
CALIBRATION`), **both** `mean_variance` and `stdev_variance` are `None` —
not a mean computed from too few points, since a mean over one or two
samples is exactly the false precision this threshold exists to prevent.
`note` always states the real count and says so plainly (e.g. "only 1 past
outcome tagged 'relocation' — too few to estimate variance; showing the
raw record instead"), never a number dressed up as more certain than it
is.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import structlog
from contracts.graph_types import Outcome

logger = structlog.get_logger(__name__)

MIN_SAMPLE_SIZE_FOR_CALIBRATION: int = 3
"""Same threshold precedent as Phase 9's Slippage Analyst N=3 — not a new
arbitrary number. Below this sample size, no numeric confidence figure is
produced; spec §11.5's own named failure mode ("Cold start... be honest")."""


@dataclass(frozen=True, slots=True)
class CalibrationEstimate:
    """Auditable output of one calibration computation — every number A39
    (or a human reviewing it) needs to check the arithmetic and the
    honesty of the thin-history call, not just a final confidence figure."""

    tag: str
    sample_size: int
    """Count of `outcomes` whose `variance` is not `None` — see this
    module's docstring, "sample size counts resolved outcomes only"."""
    mean_variance: float | None
    """`None` iff `is_thin_history`."""
    stdev_variance: float | None
    """Sample standard deviation (`statistics.stdev`, N-1 denominator).
    `None` iff `is_thin_history` or `sample_size < 2` (the latter can only
    arise if `MIN_SAMPLE_SIZE_FOR_CALIBRATION` is ever lowered below 2;
    with the current threshold of 3, `is_thin_history` already covers
    every such case)."""
    is_thin_history: bool
    """`True` iff `sample_size < MIN_SAMPLE_SIZE_FOR_CALIBRATION`."""
    note: str
    """Always populated, plain-English, honest. States the real sample
    size in every case; states mean+stdev when not thin, states the
    "too few to estimate" fact plainly when thin — never fabricates
    precision either way."""


@dataclass(frozen=True, slots=True)
class RankedOutcome:
    """One `Outcome` ranked by the magnitude of its variance — backward
    mode's honest candidate list for "likely failure point," not a
    verdict."""

    outcome: Outcome
    abs_variance: float


def _resolved_variances(outcomes: tuple[Outcome, ...]) -> list[float]:
    """The real, non-`None` `variance` values from `outcomes` — the only
    ones that carry calibration evidence."""
    return [o.variance for o in outcomes if o.variance is not None]


def _thin_history_note(tag: str, sample_size: int) -> str:
    if sample_size == 0:
        return f"no past outcomes tagged {tag!r} with a settled variance — nothing to calibrate against yet."
    plural = "outcome" if sample_size == 1 else "outcomes"
    return (
        f"only {sample_size} past {plural} tagged {tag!r} with a settled variance — too few to "
        f"estimate variance (need at least {MIN_SAMPLE_SIZE_FOR_CALIBRATION}); showing the raw "
        "record instead of a fabricated confidence figure."
    )


def _settled_note(tag: str, sample_size: int, mean_variance: float, stdev_variance: float) -> str:
    return (
        f"based on {sample_size} past outcomes tagged {tag!r} with a settled variance: "
        f"mean variance {mean_variance:.4g}, stdev {stdev_variance:.4g}."
    )


def compute_calibration(tag: str, outcomes: tuple[Outcome, ...]) -> CalibrationEstimate:
    """Computes this household's own variance calibration for one decision
    category.

    Args:
        tag: the `Outcome.attribution_tags` category this estimate is for
            (e.g. `"relocation"`) — echoed on the result for audit, not
            otherwise used to filter (the caller is expected to have
            already fetched `outcomes` for exactly this tag, typically via
            `GraphReader.outcome_variance(tag)`).
        outcomes: the `Outcome` nodes for this category. Entries with
            `variance is None` are excluded from the arithmetic (see this
            module's docstring) but do not raise — a mixed tuple of
            settled and unsettled outcomes is an expected, normal input.

    Returns:
        A `CalibrationEstimate`. `is_thin_history` is `True` and
        `mean_variance`/`stdev_variance` are both `None` whenever the
        count of *resolved* (`variance is not None`) outcomes is below
        `MIN_SAMPLE_SIZE_FOR_CALIBRATION` — including the `sample_size ==
        0` case. Never raises on empty or thin input; thin history is a
        normal, honestly-reported outcome, not an error.
    """
    variances = _resolved_variances(outcomes)
    sample_size = len(variances)
    is_thin_history = sample_size < MIN_SAMPLE_SIZE_FOR_CALIBRATION

    mean_variance: float | None = None
    stdev_variance: float | None = None
    if is_thin_history:
        note = _thin_history_note(tag, sample_size)
    else:
        mean_variance = statistics.mean(variances)
        stdev_variance = statistics.stdev(variances)
        note = _settled_note(tag, sample_size, mean_variance, stdev_variance)

    result = CalibrationEstimate(
        tag=tag,
        sample_size=sample_size,
        mean_variance=mean_variance,
        stdev_variance=stdev_variance,
        is_thin_history=is_thin_history,
        note=note,
    )
    logger.info(
        "calibration_stats.computed",
        tag=tag,
        sample_size=sample_size,
        is_thin_history=is_thin_history,
        mean_variance=mean_variance,
        stdev_variance=stdev_variance,
    )
    return result


def rank_by_absolute_variance(outcomes: tuple[Outcome, ...], *, top_n: int = 3) -> tuple[RankedOutcome, ...]:
    """For backward mode: the outcomes with the largest `|variance|` for
    this category — the honest candidates for "likely failure point," not
    a verdict (A40 Decision Synthesizer's forbidden list: "no verdict,
    only evidence-linked prediction" — ADR-017).

    Args:
        outcomes: the `Outcome` nodes for one decision category (typically
            `GraphReader.outcome_variance(tag)`'s result).
        top_n: how many ranked outcomes to return at most. Must be >= 0.

    Returns:
        Up to `top_n` `RankedOutcome`s, sorted by `abs_variance`
        descending. Outcomes whose `variance` is `None` are excluded first
        (nothing to rank). Ties broken deterministically by `outcome.id`
        ascending (lexicographic string order) — never arbitrary dict/set
        ordering, so this function's output is reproducible across runs on
        identical input.

    Raises:
        ValueError: `top_n` is negative.
    """
    if top_n < 0:
        raise ValueError(f"top_n must be >= 0, got {top_n!r}")

    ranked = [
        RankedOutcome(outcome=o, abs_variance=abs(o.variance)) for o in outcomes if o.variance is not None
    ]
    ranked.sort(key=lambda r: (-r.abs_variance, str(r.outcome.id)))
    return tuple(ranked[:top_n])


__all__ = [
    "MIN_SAMPLE_SIZE_FOR_CALIBRATION",
    "CalibrationEstimate",
    "RankedOutcome",
    "compute_calibration",
    "rank_by_absolute_variance",
]

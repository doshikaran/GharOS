"""`backend/app/solvers/calibration_stats.py` — pure-function unit tests,
no Firestore emulator needed (this module does no graph I/O). Every
non-thin-history statistic is checked against an independent, hand-worked
arithmetic computation in the test itself (same discipline as Phase 8's
`verify_ef1`), not just "assert equals whatever the code produces".
"""

from __future__ import annotations

import math

import pytest
from contracts.graph_types import NodeId, Outcome

from app.solvers.calibration_stats import (
    MIN_SAMPLE_SIZE_FOR_CALIBRATION,
    CalibrationEstimate,
    RankedOutcome,
    compute_calibration,
    rank_by_absolute_variance,
)
from tests.conftest import make_provenance

TAG = "relocation"


def _outcome(node_id: str, *, variance: float | None, tags: tuple[str, ...] = (TAG,)) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=make_provenance(),
        predicted="predicted",
        actual="actual",
        variance=variance,
        attribution_tags=tags,
    )


class TestMinSampleSizeConstant:
    def test_is_three_same_precedent_as_slippage_analyst(self) -> None:
        assert MIN_SAMPLE_SIZE_FOR_CALIBRATION == 3


class TestComputeCalibrationThinHistory:
    def test_n_equals_zero_no_outcomes_at_all(self) -> None:
        result = compute_calibration(TAG, ())
        assert result == CalibrationEstimate(
            tag=TAG,
            sample_size=0,
            mean_variance=None,
            stdev_variance=None,
            is_thin_history=True,
            note=result.note,
        )
        assert "no past outcomes" in result.note
        assert "relocation" in result.note

    def test_n_equals_zero_when_every_outcome_has_unsettled_variance(self) -> None:
        """`variance=None` outcomes (prediction not yet scored) never
        count toward sample_size, even when outcomes are present."""
        outcomes = (_outcome("o1", variance=None), _outcome("o2", variance=None))
        result = compute_calibration(TAG, outcomes)
        assert result.sample_size == 0
        assert result.is_thin_history is True
        assert result.mean_variance is None
        assert result.stdev_variance is None

    def test_n_equals_one(self) -> None:
        outcomes = (_outcome("o1", variance=4.0),)
        result = compute_calibration(TAG, outcomes)
        assert result.sample_size == 1
        assert result.is_thin_history is True
        assert result.mean_variance is None
        assert result.stdev_variance is None
        assert "only 1 past outcome" in result.note
        assert "too few to estimate variance" in result.note

    def test_n_equals_two_stdev_must_be_none(self) -> None:
        outcomes = (_outcome("o1", variance=1.0), _outcome("o2", variance=3.0))
        result = compute_calibration(TAG, outcomes)
        assert result.sample_size == 2
        assert result.is_thin_history is True
        assert result.mean_variance is None
        assert result.stdev_variance is None
        assert "only 2 past outcomes" in result.note

    def test_unresolved_outcomes_excluded_from_count_alongside_resolved_ones(self) -> None:
        outcomes = (
            _outcome("o1", variance=1.0),
            _outcome("o2", variance=None),
        )
        result = compute_calibration(TAG, outcomes)
        assert result.sample_size == 1
        assert result.is_thin_history is True


class TestComputeCalibrationBoundary:
    def test_n_equals_three_exactly_is_not_thin(self) -> None:
        """Hand-computed: variances [2.0, 4.0, 6.0] -> mean = 12/3 = 4.0;
        sample stdev (N-1 denominator): deviations -2, 0, 2 -> squared 4,
        0, 4 -> sum 8 -> /(3-1)=2 -> variance 4.0 -> stdev = sqrt(4.0) =
        2.0 exactly."""
        outcomes = (
            _outcome("o1", variance=2.0),
            _outcome("o2", variance=4.0),
            _outcome("o3", variance=6.0),
        )
        result = compute_calibration(TAG, outcomes)
        assert result.sample_size == 3
        assert result.is_thin_history is False
        assert result.mean_variance is not None
        assert result.stdev_variance is not None
        assert math.isclose(result.mean_variance, 4.0)
        assert math.isclose(result.stdev_variance, 2.0)
        assert "based on 3 past outcomes" in result.note
        assert "mean variance 4" in result.note


class TestComputeCalibrationSettled:
    def test_n_greater_than_three_hand_computed_mean_and_stdev(self) -> None:
        """Hand-computed independently of the implementation:

        variances = [1.0, 2.0, 3.0, 4.0]
        mean = (1+2+3+4)/4 = 10/4 = 2.5
        deviations from mean: -1.5, -0.5, 0.5, 1.5
        squared deviations: 2.25, 0.25, 0.25, 2.25 -> sum = 5.0
        sample variance (N-1 = 3 denominator): 5.0 / 3 = 1.666...
        sample stdev = sqrt(5/3) = 1.2909944487358056...
        """
        outcomes = (
            _outcome("o1", variance=1.0),
            _outcome("o2", variance=2.0),
            _outcome("o3", variance=3.0),
            _outcome("o4", variance=4.0),
        )
        result = compute_calibration(TAG, outcomes)

        expected_mean = 2.5
        expected_stdev = math.sqrt(5.0 / 3.0)

        assert result.sample_size == 4
        assert result.is_thin_history is False
        assert result.mean_variance is not None
        assert result.stdev_variance is not None
        assert math.isclose(result.mean_variance, expected_mean, rel_tol=1e-12)
        assert math.isclose(result.stdev_variance, expected_stdev, rel_tol=1e-12)

    def test_negative_and_positive_variances_mix(self) -> None:
        """variances = [-2.0, 0.0, 2.0] -> mean = 0.0; deviations -2, 0, 2
        -> squared 4, 0, 4 -> sum 8 -> /2 = 4.0 -> stdev = 2.0."""
        outcomes = (
            _outcome("o1", variance=-2.0),
            _outcome("o2", variance=0.0),
            _outcome("o3", variance=2.0),
        )
        result = compute_calibration(TAG, outcomes)
        assert result.mean_variance is not None
        assert result.stdev_variance is not None
        assert math.isclose(result.mean_variance, 0.0, abs_tol=1e-12)
        assert math.isclose(result.stdev_variance, 2.0)

    def test_tag_is_echoed_on_the_result(self) -> None:
        outcomes = (
            _outcome("o1", variance=1.0),
            _outcome("o2", variance=1.0),
            _outcome("o3", variance=1.0),
        )
        result = compute_calibration("school_transition", outcomes)
        assert result.tag == "school_transition"


class TestRankByAbsoluteVariance:
    def test_ranks_by_absolute_magnitude_descending(self) -> None:
        outcomes = (
            _outcome("o-small", variance=1.0),
            _outcome("o-large-negative", variance=-10.0),
            _outcome("o-medium", variance=5.0),
        )
        ranked = rank_by_absolute_variance(outcomes, top_n=3)
        assert [r.outcome.id for r in ranked] == [
            NodeId("o-large-negative"),
            NodeId("o-medium"),
            NodeId("o-small"),
        ]
        assert [r.abs_variance for r in ranked] == [10.0, 5.0, 1.0]

    def test_excludes_outcomes_with_unresolved_variance(self) -> None:
        outcomes = (
            _outcome("o1", variance=None),
            _outcome("o2", variance=7.0),
        )
        ranked = rank_by_absolute_variance(outcomes)
        assert len(ranked) == 1
        assert ranked[0].outcome.id == NodeId("o2")

    def test_top_n_limits_result_count(self) -> None:
        outcomes = tuple(_outcome(f"o{i}", variance=float(i)) for i in range(10))
        ranked = rank_by_absolute_variance(outcomes, top_n=2)
        assert len(ranked) == 2
        assert ranked[0].abs_variance == 9.0
        assert ranked[1].abs_variance == 8.0

    def test_default_top_n_is_three(self) -> None:
        outcomes = tuple(_outcome(f"o{i}", variance=float(i)) for i in range(10))
        ranked = rank_by_absolute_variance(outcomes)
        assert len(ranked) == 3

    def test_deterministic_tie_break_by_outcome_id(self) -> None:
        """Two outcomes tie on |variance| = 3.0 -> broken by NodeId string
        ascending, never arbitrary dict/set ordering."""
        outcomes = (
            _outcome("o-zzz", variance=3.0),
            _outcome("o-aaa", variance=-3.0),
            _outcome("o-mmm", variance=10.0),
        )
        ranked = rank_by_absolute_variance(outcomes, top_n=3)
        assert [r.outcome.id for r in ranked] == [
            NodeId("o-mmm"),
            NodeId("o-aaa"),
            NodeId("o-zzz"),
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert rank_by_absolute_variance(()) == ()

    def test_top_n_zero_returns_empty(self) -> None:
        outcomes = (_outcome("o1", variance=1.0),)
        assert rank_by_absolute_variance(outcomes, top_n=0) == ()

    def test_negative_top_n_raises(self) -> None:
        with pytest.raises(ValueError, match="top_n"):
            rank_by_absolute_variance((), top_n=-1)

    def test_result_type_is_ranked_outcome(self) -> None:
        outcomes = (_outcome("o1", variance=2.0),)
        ranked = rank_by_absolute_variance(outcomes)
        assert isinstance(ranked[0], RankedOutcome)

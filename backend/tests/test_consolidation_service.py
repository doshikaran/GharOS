"""Memory Consolidation service (`app.graph.consolidation_service`) —
PHASES.md Phase 14, ADR-021 Decision 3.

Proves:
- The full sequence runs in order: A10 (Pattern Miner) then A11 (Graph
  Maintainer) then, if wired, E2's constraint-promotion and vendor-
  reliability callbacks.
- Both E2 callbacks are genuinely optional — a service built without them
  still runs A10/A11 correctly and reports `None` honestly, never a
  fabricated zero standing in for "not wired."
- The returned `ConsolidationRunResult` reflects real subsystem output
  (pattern count, obligations flagged, integrity violations) — not a bare
  success boolean — using real `PatternMiner`/`GraphMaintainer` instances
  wired to fakes, not a reimplementation of either.

Ordering is proven with minimal duck-typed test doubles (`_OrderRecording
PatternMiner`/`_OrderRecordingGraphMaintainer`) satisfying
`ConsolidationService`'s own narrow `_PatternMinerPort`/
`_GraphMaintainerPort` Protocols — composition, not subclassing either
real class.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import AgentId, Derivation, NodeId, Outcome, Pattern, Provenance

from app.graph.consolidation_service import (
    ConsolidationService,
    ConstraintPromotionSummary,
    VendorReliabilitySummary,
)
from app.graph.graph_maintainer import GraphMaintainer, MaintenanceRunResult
from app.graph.pattern_miner import PatternMiner
from app.reasoning.gemini_client import GeminiClient

from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_pattern_repository import FakePatternRepository
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _FakeIntegrityChecker:
    def __init__(self, *, violations: tuple[str, ...] = ()) -> None:
        self._violations = violations
        self.check_calls: list[str] = []

    def check(self, scope: str) -> tuple[str, ...]:
        self.check_calls.append(scope)
        return self._violations


class _EmptyStore:
    """Minimal stand-in for `FirestoreGraphStore` — `GraphMaintainer.run`
    always calls `flagged_for_review`, which calls `all_current_nodes`,
    even when this test suite has nothing to say about staleness. Real,
    honest behaviour (an empty graph has no stale obligations), not a
    method left unimplemented."""

    def all_current_nodes(self, node_types: tuple[type, ...] | None = None) -> tuple[object, ...]:
        return ()


class _OrderRecordingPatternMiner:
    """Satisfies `ConsolidationService`'s `_PatternMinerPort` Protocol by
    composition, not inheritance — records that A10 ran, then delegates
    to a real `PatternMiner` so its actual behaviour (the threshold gate,
    the write) is still exercised for real."""

    def __init__(self, *, real_miner: PatternMiner, sequence: list[str]) -> None:
        self._real_miner = real_miner
        self._sequence = sequence

    def run(self, *, now: datetime | None = None) -> tuple[Pattern, ...]:
        self._sequence.append("A10")
        return self._real_miner.run(now=now)


class _OrderRecordingGraphMaintainer:
    """See `_OrderRecordingPatternMiner` — same pattern for A11."""

    def __init__(self, *, real_maintainer: GraphMaintainer, sequence: list[str]) -> None:
        self._real_maintainer = real_maintainer
        self._sequence = sequence

    def run(self, *, now: datetime | None = None) -> MaintenanceRunResult:
        self._sequence.append("A11")
        return self._real_maintainer.run(now=now)


def _real_pattern_miner(*, outcomes_by_tag: dict[str, tuple[Outcome, ...]] | None = None) -> PatternMiner:
    reader = FakeGraphReader(outcome_variance_by_tag=outcomes_by_tag or {})
    pattern_repo = FakePatternRepository()
    fake_models = FakeModels(texts=["Appointments on Monday slip 75% of the time."])
    client = GeminiClient(router=fake_router(fake_models))
    return PatternMiner(graph_reader=reader, pattern_repository=pattern_repo, gemini_client=client)


def _real_graph_maintainer(*, violations: tuple[str, ...] = ()) -> GraphMaintainer:
    return GraphMaintainer(
        store=_EmptyStore(),  # type: ignore[arg-type]
        integrity_checker=_FakeIntegrityChecker(violations=violations),
        graph_writer=FakeGraphWriter(),
    )


def _outcome(node_id: str, *, variance: float) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.8,
            deriving_agent=AgentId("A26"),
            created_at=_NOW,
        ),
        predicted="on schedule",
        actual="see variance",
        variance=variance,
        attribution_tags=("scheduled_monday",),
    )


class TestRunOrderAndOptionalCallbacks:
    def test_a10_then_a11_when_no_callbacks_wired(self) -> None:
        sequence: list[str] = []
        service = ConsolidationService(
            pattern_miner=_OrderRecordingPatternMiner(real_miner=_real_pattern_miner(), sequence=sequence),
            graph_maintainer=_OrderRecordingGraphMaintainer(
                real_maintainer=_real_graph_maintainer(), sequence=sequence
            ),
        )

        result = service.run(now=_NOW)

        assert sequence == ["A10", "A11"]
        assert result.constraint_promotion is None
        assert result.vendor_reliability is None
        assert result.patterns_mined == ()
        assert result.maintenance.integrity_violations == ()

    def test_full_sequence_with_both_callbacks_wired(self) -> None:
        sequence: list[str] = []
        constraint_summary = ConstraintPromotionSummary(
            candidates_created=1,
            candidate_approval_request_ids=("approval-x",),
            notes="one repeated dietary mention promoted for confirmation",
        )
        vendor_summary = VendorReliabilitySummary(
            vendors_scored=2, updated_vendor_ids=("vendor-a",), notes="2 vendors scored, 1 changed"
        )

        def promote() -> ConstraintPromotionSummary:
            sequence.append("constraint_promotion")
            return constraint_summary

        def score() -> VendorReliabilitySummary:
            sequence.append("vendor_reliability")
            return vendor_summary

        service = ConsolidationService(
            pattern_miner=_OrderRecordingPatternMiner(real_miner=_real_pattern_miner(), sequence=sequence),
            graph_maintainer=_OrderRecordingGraphMaintainer(
                real_maintainer=_real_graph_maintainer(), sequence=sequence
            ),
            promote_constraints=promote,
            score_vendor_reliability=score,
        )

        result = service.run(now=_NOW)

        assert sequence == ["A10", "A11", "constraint_promotion", "vendor_reliability"]
        assert result.constraint_promotion == constraint_summary
        assert result.vendor_reliability == vendor_summary
        assert result.ran_at == _NOW

    def test_only_constraint_promotion_wired_vendor_stays_none(self) -> None:
        sequence: list[str] = []
        constraint_summary = ConstraintPromotionSummary(
            candidates_created=0, candidate_approval_request_ids=(), notes="nothing repeated this run"
        )

        def promote() -> ConstraintPromotionSummary:
            sequence.append("constraint_promotion")
            return constraint_summary

        service = ConsolidationService(
            pattern_miner=_OrderRecordingPatternMiner(real_miner=_real_pattern_miner(), sequence=sequence),
            graph_maintainer=_OrderRecordingGraphMaintainer(
                real_maintainer=_real_graph_maintainer(), sequence=sequence
            ),
            promote_constraints=promote,
        )

        result = service.run(now=_NOW)

        assert sequence == ["A10", "A11", "constraint_promotion"]
        assert result.constraint_promotion == constraint_summary
        assert result.vendor_reliability is None


class TestResultReflectsRealSubsystemOutput:
    def test_pattern_and_integrity_counts_are_real_not_fabricated(self) -> None:
        outcomes = (
            _outcome("o1", variance=50.0),
            _outcome("o2", variance=50.0),
            _outcome("o3", variance=50.0),
            _outcome("o4", variance=0.0),
        )
        miner = _real_pattern_miner(outcomes_by_tag={"scheduled_monday": outcomes})
        maintainer = _real_graph_maintainer(violations=("node x: missing provenance",))
        service = ConsolidationService(pattern_miner=miner, graph_maintainer=maintainer)

        result = service.run(now=_NOW)

        assert len(result.patterns_mined) == 1
        assert result.patterns_mined[0].support_count == 4
        assert result.maintenance.integrity_violations == ("node x: missing provenance",)

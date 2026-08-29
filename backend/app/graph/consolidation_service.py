"""Memory Consolidation service (spec §20; PHASES.md Phase 14; ADR-021
Decision 3) — the single off-peak orchestrator E3 wires a Cloud Scheduler
job (`gharos-consolidation-nightly`) into via `job_name` dispatch
(ADR-021 Decision 3 — no `contracts.events.SubsystemName` addition
needed).

Runs, in sequence, exactly as ADR-021 specifies:

1. A10 Pattern Miner (`app.graph.pattern_miner.PatternMiner.run`)
2. A11 Graph Maintainer (`app.graph.graph_maintainer.GraphMaintainer.run`)
3. E2's constraint-promotion entry point (optional, injected)
4. E2's vendor-reliability-scoring entry point (optional, injected)

## The interface E2 (and E3, wiring the real trigger) integrate against

**E1 does not have E2's final constraint-promotion/vendor-reliability
code this phase** (ADR-021: both are being built in parallel this
session). Rather than guess at E2's internal shape, this module defines
the exact, minimal, injectable callback contract it needs and depends on
nothing more:

- `ConstraintPromotionFn = Callable[[], ConstraintPromotionSummary]` — a
  zero-argument callable. E2's real constraint-promotion pass (ADR-021
  Decision 4: scans repeated signals, e.g. repeated dietary mentions,
  writes a candidate hard `Constraint` proposal through the existing
  `ApprovalRequest`/Approval Gate mechanism, confirmation-gated, never a
  live constraint on its own) is called with no arguments and must
  return a `ConstraintPromotionSummary`.
- `VendorReliabilityFn = Callable[[], VendorReliabilitySummary]` —
  likewise, for E2's real vendor-reliability scoring pass (ADR-021
  Decision 5: a deterministic function over `Outcome.attribution_tags`
  and `response_latency_hours`, written to `Vendor.reliability_score`/
  `Vendor.response_latency_hours` via `supersede_node`).

Both are **optional** constructor arguments (`None` by default) — a
`ConsolidationService` built before E2's real callables exist (e.g. in
this phase's own tests, or in a deploy that lands before E2's code) still
runs A10 and A11 correctly and reports `constraint_promotion=None`/
`vendor_reliability=None` honestly in its result, never a fabricated
"0 processed" standing in for "not wired yet."

`ConstraintPromotionSummary`/`VendorReliabilitySummary` are **not**
`contracts/` types — they are this module's own small, local return-value
shapes (the same status as `app.solvers.calibration_stats.
CalibrationEstimate`: a real, structured, documented contract between two
specific pieces of code, not a graph type). E2 is free to have their own
richer internal result type and adapt it to this shape at the call site
(e.g. a small lambda/wrapper), whichever is more natural for E2's own
module — E2's call, per ADR-021's own phrasing for this exact interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog
from contracts.graph_types import Pattern

from app.graph.graph_maintainer import GraphMaintainer, MaintenanceRunResult
from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.pattern_miner import PatternMiner
from app.graph.pattern_repository import FirestorePatternRepository
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_client import create_firestore_client
from app.persistence.firestore_store import FirestoreGraphStore
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import get_settings

logger = structlog.get_logger(__name__)


class _PatternMinerPort(Protocol):
    """The one method this service needs from A10 — narrower than
    depending on the concrete `app.graph.pattern_miner.PatternMiner`
    class, per this project's own hexagonal/ports-and-adapters
    convention (gharos-standards: depend on the minimal interface a
    caller needs, not a concrete implementation). `PatternMiner`
    structurally satisfies this; so does any test double with a matching
    `run` method — no inheritance required."""

    def run(self, *, now: datetime | None = None) -> tuple[Pattern, ...]: ...


class _GraphMaintainerPort(Protocol):
    """The one method this service needs from A11 — see
    `_PatternMinerPort`'s docstring for why this is a local Protocol
    rather than the concrete `app.graph.graph_maintainer.GraphMaintainer`
    class."""

    def run(self, *, now: datetime | None = None) -> MaintenanceRunResult: ...


@dataclass(frozen=True, slots=True)
class ConstraintPromotionSummary:
    """The shape E1's Consolidation Service needs back from E2's
    constraint-promotion entry point (ADR-021 Decision 4). See module
    docstring — not a `contracts/` type."""

    candidates_created: int
    """How many new candidate hard `Constraint` proposals were opened for
    human confirmation this run (via the Approval Gate) — `0` is a real,
    valid, common outcome (no repeated signal cleared E2's own bar this
    run), never treated as an error by this service."""
    candidate_approval_request_ids: tuple[str, ...]
    """The `ApprovalRequest` ids opened, for audit traceability from this
    run's log line back to the specific pending confirmations it
    created."""
    notes: str
    """Plain-English summary of what ran, always populated (mirrors
    `calibration_stats.CalibrationEstimate.note`'s "always honest, never
    blank" convention)."""


@dataclass(frozen=True, slots=True)
class VendorReliabilitySummary:
    """The shape E1's Consolidation Service needs back from E2's
    vendor-reliability-scoring entry point (ADR-021 Decision 5). See
    module docstring — not a `contracts/` type."""

    vendors_scored: int
    """How many `Vendor` nodes had `reliability_score`/
    `response_latency_hours` recomputed and (if changed)
    `supersede_node`-written this run."""
    updated_vendor_ids: tuple[str, ...]
    """Ids of the `Vendor` nodes actually superseded this run (a vendor
    scored but unchanged from its prior value need not appear here — E2's
    call on what counts as "updated")."""
    notes: str
    """Always populated, plain-English — see `ConstraintPromotionSummary.
    notes`."""


ConstraintPromotionFn = Callable[[], ConstraintPromotionSummary]
VendorReliabilityFn = Callable[[], VendorReliabilitySummary]


@dataclass(frozen=True, slots=True)
class ConsolidationRunResult:
    """The real, structured, inspectable output of one full consolidation
    run — this is what gets logged as the "genuine overnight run"
    evidence PHASES.md Gate 14 requires (a real Cloud Logging line
    carrying this shape, not a bare success boolean)."""

    ran_at: datetime
    patterns_mined: tuple[Pattern, ...]
    maintenance: MaintenanceRunResult
    constraint_promotion: ConstraintPromotionSummary | None
    """`None` iff no `promote_constraints` callable was injected — see
    module docstring."""
    vendor_reliability: VendorReliabilitySummary | None
    """`None` iff no `score_vendor_reliability` callable was injected —
    see module docstring."""


class ConsolidationService:
    """The single off-peak Memory Consolidation orchestrator (spec §20).
    Dependency-injected on the two E1-owned components it always runs
    (structurally, `PatternMiner`/`GraphMaintainer` — see
    `_PatternMinerPort`/`_GraphMaintainerPort`) and the two E2-owned entry
    points it optionally calls out to."""

    def __init__(
        self,
        *,
        pattern_miner: _PatternMinerPort,
        graph_maintainer: _GraphMaintainerPort,
        promote_constraints: ConstraintPromotionFn | None = None,
        score_vendor_reliability: VendorReliabilityFn | None = None,
    ) -> None:
        self._pattern_miner = pattern_miner
        self._graph_maintainer = graph_maintainer
        self._promote_constraints = promote_constraints
        self._score_vendor_reliability = score_vendor_reliability

    def run(self, *, now: datetime | None = None) -> ConsolidationRunResult:
        """Runs the full sequence: A10, then A11, then (if wired) E2's
        two entry points, in that order (ADR-021 Decision 3).

        Args:
            now: the reference time for this run — defaults to
                `datetime.now(UTC)`, injected so tests and any caller
                needing a pinned timestamp can control it.

        Returns:
            A `ConsolidationRunResult` carrying every real number this
            run produced. Never raises for a component reporting "found
            nothing" (empty patterns, zero obligations flagged, a clean
            integrity check, or an unwired E2 callback) — those are all
            honest, expected outcomes, not failures.
        """
        reference_time = now if now is not None else datetime.now(UTC)

        patterns = self._pattern_miner.run(now=reference_time)
        maintenance = self._graph_maintainer.run(now=reference_time)
        constraint_result = self._promote_constraints() if self._promote_constraints is not None else None
        vendor_result = (
            self._score_vendor_reliability() if self._score_vendor_reliability is not None else None
        )

        result = ConsolidationRunResult(
            ran_at=reference_time,
            patterns_mined=patterns,
            maintenance=maintenance,
            constraint_promotion=constraint_result,
            vendor_reliability=vendor_result,
        )
        logger.info(
            "consolidation_service.run_completed",
            ran_at=reference_time.isoformat(),
            patterns_mined=len(patterns),
            obligations_flagged=len(maintenance.obligations_flagged),
            integrity_violations=len(maintenance.integrity_violations),
            constraint_promotion_wired=constraint_result is not None,
            vendor_reliability_wired=vendor_result is not None,
        )
        return result


def run_nightly_consolidation(*, cycle_label: str) -> ConsolidationRunResult:
    """The real, production composition root for one off-peak
    consolidation cycle — the exact entry point
    `app.api.pubsub_receiver._default_consolidation_runner` (E3) already
    documents and lazily imports (ADR-021 Decision 3: Cloud Scheduler ->
    Pub/Sub -> this receiver -> here). Builds every real dependency from
    `app.settings.get_settings()` (the same composition-root pattern
    `app.api.debug.get_model_router`/`get_gemini_client` already use for
    a live Gemini call), runs one full `ConsolidationService.run()` pass,
    and returns its result untouched.

    Args:
        cycle_label: identifies this run for logging (e.g. the date the
            Cloud Scheduler tick carried as `ScheduledTickPayload.
            cycle_label` — ADR-021 Decision 3). Not otherwise used in the
            run itself; `ConsolidationService.run()` always evaluates
            staleness/integrity against the real current time.

    **E2's constraint-promotion / vendor-reliability callbacks are
    intentionally left unwired here (`promote_constraints=None`,
    `score_vendor_reliability=None`).** As of this phase, `app.reasoning`/
    `app.graph` carries no such module yet (ADR-021: E2's two entry
    points are landing in parallel this same session, exact module path
    "E2's call"). This is an ordinary cross-role landing-order dependency,
    not a shortcut against a stated standard — `docs/DEBT.md` does not
    apply. When E2's module lands, wiring it here is a small, expected,
    mechanical follow-up (two more lines: an import plus two keyword
    arguments), exactly the "same seam as Phase 13's E3/E2 dispatch"
    precedent this function's caller already documents. Until then, a
    real nightly run still executes A10 and A11 for real and reports
    `constraint_promotion=None`/`vendor_reliability=None` honestly —
    never a fabricated result standing in for the unwired pair.
    """
    settings = get_settings()
    firestore_client = create_firestore_client(settings)
    store = FirestoreGraphStore(firestore_client)

    reader = FirestoreGraphReader(store)
    graph_writer = FirestoreGraphWriter(store)
    pattern_repository = FirestorePatternRepository(store)
    integrity_checker = FirestoreGraphIntegrityChecker(store)

    model_router = ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        location_pro=settings.vertex_ai_location_pro,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )
    gemini_client = GeminiClient(router=model_router)

    pattern_miner = PatternMiner(
        graph_reader=reader, pattern_repository=pattern_repository, gemini_client=gemini_client
    )
    graph_maintainer = GraphMaintainer(
        store=store, integrity_checker=integrity_checker, graph_writer=graph_writer
    )
    service = ConsolidationService(
        pattern_miner=pattern_miner,
        graph_maintainer=graph_maintainer,
        promote_constraints=None,
        score_vendor_reliability=None,
    )

    reference_time = datetime.now(UTC)
    logger.info("consolidation_service.nightly_run_starting", cycle_label=cycle_label)
    result = service.run(now=reference_time)
    logger.info(
        "consolidation_service.nightly_run_finished",
        cycle_label=cycle_label,
        patterns_mined=len(result.patterns_mined),
        obligations_flagged=len(result.maintenance.obligations_flagged),
        integrity_violations=len(result.maintenance.integrity_violations),
    )
    return result


__all__ = [
    "ConsolidationRunResult",
    "ConsolidationService",
    "ConstraintPromotionFn",
    "ConstraintPromotionSummary",
    "VendorReliabilityFn",
    "VendorReliabilitySummary",
    "run_nightly_consolidation",
]

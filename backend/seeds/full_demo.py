"""`build_full_demo()` — the complete 4-minute-demo dataset
(`PHASES.md` Phase 15, E1; `GharOS_Build_Spec_v2.md` §24 / §26).

It is `seeds.demo_household.build_demo_household()` (the frozen Phase 1
graph-machinery proof) plus every `seeds.segments` slice, aggregated into
one `SeedResult`:

    base household + roster completion + 12 ugly documents
    + three months of financial signals and the money leak
    + the engineered verification receipt
    + the Household Council car decision
    + enough OUTCOME history for the calibration panel

Pure data, no I/O. `seeds.seed_loader.load_full_demo(writer)` writes it
through the real provenance-guarded `FirestoreGraphWriter`; `python -m
seeds load` is the CLI over that.

Why a separate builder rather than extending `build_demo_household()`:
the base builder is what the whole emulator-backed test suite's `seeded`
fixture loads, with many exact-count / exact-set assertions against it.
The demo dataset is a strict superset with its own new consumers (the
demo-beat assertions in `backend/tests/test_full_demo_seed.py`), so it
composes onto the base rather than destabilising it - the same discipline
the ADR trail applies to every other "add against a real consumer" change.
"""

from __future__ import annotations

from contracts.graph_types import Edge

from seeds.demo_household import SeedResult, build_demo_household
from seeds.segments import (
    calibration,
    council,
    documents,
    finance,
    roster,
    verification,
)
from seeds.segments._common import Segment

_SEGMENT_BUILDERS = (
    roster.build,
    documents.build,
    finance.build,
    verification.build,
    council.build,
    calibration.build,
)


def build_full_demo() -> SeedResult:
    """Builds (does not write) the full demo household graph."""
    base = build_demo_household()

    nodes: list[object] = list(base.nodes)
    edges: list[Edge] = list(base.edges)

    for builder in _SEGMENT_BUILDERS:
        segment: Segment = builder()
        nodes.extend(segment.nodes)
        edges.extend(segment.edges)

    _assert_unique_ids(nodes, edges, base)

    return SeedResult(
        nodes=tuple(nodes),
        edges=tuple(edges),
        supersession=base.supersession,
    )


def _assert_unique_ids(nodes: list[object], edges: list[Edge], base: SeedResult) -> None:
    """Fail loudly at build time on any id collision between the base and a
    segment, or between two segments - a duplicate id would otherwise be a
    silent last-writer-wins overwrite at load time."""
    node_ids = [str(n.id) for n in nodes] + [str(base.supersession[1].id)]  # type: ignore[attr-defined]
    _dupes(node_ids, "node")
    _dupes([str(e.id) for e in edges], "edge")


def _dupes(ids: list[str], kind: str) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            dupes.add(identifier)
        seen.add(identifier)
    if dupes:
        raise ValueError(f"full demo seed has duplicate {kind} ids: {sorted(dupes)}")


__all__ = ["build_full_demo"]

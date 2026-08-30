"""Composable Phase 15 demo-seed segments (`PHASES.md` Phase 15, E1).

Each module here builds one slice of the full 4-minute-demo dataset
(`GharOS_Build_Spec_v2.md` §24 / §26) as plain data — no I/O — and returns
a `Segment` (`nodes`, `edges`). `seeds.full_demo.build_full_demo`
aggregates the Phase 1 machinery-proof base (`seeds.demo_household.
build_demo_household`) with every segment here into one `SeedResult`.

Kept out of `seeds.demo_household` deliberately: that module is the frozen
Phase 1 proof the whole emulator-backed test suite's `seeded` fixture
loads, with dozens of exact-set assertions against it. The Phase 15 demo
dataset is a strict superset with its own new consumers, so it composes
*onto* the base rather than mutating it — the same "add against a real
consumer, never destabilise the frozen thing" discipline the ADR trail
applies everywhere else.
"""

from __future__ import annotations

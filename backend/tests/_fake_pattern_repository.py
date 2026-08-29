"""A minimal, in-memory `contracts.repositories.PatternRepository` test
double — for Phase 14's A10 Pattern Miner unit tests
(`test_pattern_miner.py`) that need a real object satisfying the
`PatternRepository` Protocol without a Firestore emulator (the real,
provenance-guarded, Firestore-backed proof lives in
`test_pattern_miner.py`'s own emulator-backed integration test, run
against `app.graph.pattern_repository.FirestorePatternRepository`).

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_fake_graph_writer.py`/`_fake_graph_reader.py`'s established
pattern.
"""

from __future__ import annotations

from contracts.graph_types import NodeId, Pattern


class FakePatternRepository:
    """Structurally satisfies `contracts.repositories.PatternRepository`.
    Records every write in call order — this fake exists to let A10's
    unit tests prove *whether and what* gets written, in particular that
    a below-threshold candidate never reaches `write_pattern` at all."""

    def __init__(self) -> None:
        self._patterns: dict[NodeId, Pattern] = {}
        self.write_pattern_calls: list[Pattern] = []

    def all_patterns(self) -> tuple[Pattern, ...]:
        return tuple(self._patterns.values())

    def write_pattern(self, pattern: Pattern) -> NodeId:
        self.write_pattern_calls.append(pattern)
        self._patterns[pattern.id] = pattern
        return pattern.id


__all__ = ["FakePatternRepository"]

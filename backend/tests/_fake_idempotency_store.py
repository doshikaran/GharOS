"""An in-memory `contracts.repositories.IdempotencyStore` test double —
for unit tests that need a real, working idempotency store without a
network call (the real, Firestore-backed replay-safety proof lives in
`test_graph_write_tool.py` / `test_approval_gate.py`, run against the
Firestore emulator via `conftest.py`'s `idempotency_store` fixture).

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py`'s established pattern.
"""

from __future__ import annotations


class InMemoryIdempotencyStore:
    """Structurally satisfies `contracts.repositories.IdempotencyStore`,
    matching `app.persistence.idempotency_store.FirestoreIdempotencyStore`'s
    exact two-step reserve/complete semantics, in a plain `dict`."""

    def __init__(self) -> None:
        self._completed: dict[str, str] = {}
        self._reserved: set[str] = set()
        self.reserve_calls = 0
        self.record_calls = 0

    def check_and_reserve(self, key: str) -> str | None:
        self.reserve_calls += 1
        if key in self._completed:
            return self._completed[key]
        self._reserved.add(key)
        return None

    def record_result(self, key: str, result_ref: str) -> None:
        self.record_calls += 1
        if key in self._completed and self._completed[key] != result_ref:
            raise ValueError(f"idempotency key {key!r} already completed with a different result")
        self._completed[key] = result_ref


__all__ = ["InMemoryIdempotencyStore"]

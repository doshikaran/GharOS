"""`GraphReadTool` — the concrete T0 tool, reusing Phase 1-4's
`contracts.repositories.GraphReader` as its backing implementation (Phase 5
task item 1: "T0 — reuse Phase 1-4's GraphReader as the backing T0 tool").

Deliberately a thin dispatch wrapper, not a reimplementation: every one of
`GraphReader`'s 14 query operations (spec §5.7) already exists, tested,
against the real Firestore emulator (`app.graph.reader.FirestoreGraphReader`,
Phase 1/4). This module's only job is to expose that read surface through
the `contracts.tools.Tool` / `ReadOnlyTool` shape the tool-tier layer needs,
so a `ToolRegistry` can hand a reasoning agent T0 access without handing it
a raw `GraphReader` (and therefore without giving that agent any path to a
write method — `GraphReader` has none).
"""

from __future__ import annotations

from datetime import datetime

from contracts.actions import ActionResult
from contracts.errors import ToolFailure
from contracts.graph_types import EdgeType, NodeId
from contracts.repositories import GraphReader
from contracts.tools import PermissionTier

_OPERATIONS = (
    "get_node",
    "neighbours",
    "path",
    "blast_radius",
    "conflicts",
    "load",
    "series",
    "history",
    "decisions_touching",
    "concession_ledger",
    "unexplained",
    "unverified",
    "expected_but_absent",
    "spend_by_category",
    "effort_evidence",
)
"""Every `GraphReader` operation this tool can dispatch to — the 14 from
spec §5.7 plus `get_node`, the one basic-lookup primitive `GraphReader`
also exposes."""


class GraphReadTool:
    """Structurally satisfies `contracts.tools.ReadOnlyTool` (and therefore
    `contracts.tools.Tool`). See `app.tools.conformance` for the
    structural-conformance proof.
    """

    def __init__(self, *, graph_reader: GraphReader, name: str = "graph_reader") -> None:
        self.name = name
        self.tier: PermissionTier = PermissionTier.T0_READ
        self._reader = graph_reader

    def invoke(self, **kwargs: object) -> ActionResult[object]:
        """Dispatches on `kwargs["operation"]` (one of `_OPERATIONS`) to the
        matching `GraphReader` method.

        Raises:
            ToolFailure: `operation` is missing/unknown, a required
                argument for the requested operation is missing or the
                wrong type, or the underlying `GraphReader` call itself
                raised (never swallowed — safety invariant #7).
        """
        operation = kwargs.get("operation")
        if operation not in _OPERATIONS:
            raise ToolFailure(
                tool_name=self.name,
                reason=f"unknown or missing operation {operation!r}; expected one of {_OPERATIONS}",
                retryable=False,
            )
        try:
            result = self._dispatch(operation, kwargs)
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — the tool boundary: any underlying
            # failure (Firestore connectivity, a malformed kwarg reaching the
            # real reader) is converted to the one sanctioned failure signal
            # (contracts.errors.ToolFailure) rather than propagating an
            # unclassified exception past this tool's callers.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc
        return ActionResult.success(result)

    def _dispatch(self, operation: str, kwargs: dict[str, object]) -> object:
        reader = self._reader
        if operation == "get_node":
            return reader.get_node(_require_node_id(kwargs, "node_id"))
        if operation == "neighbours":
            return reader.neighbours(
                _require_node_id(kwargs, "node_id"), _require_edge_type(kwargs, "edge_type")
            )
        if operation == "path":
            return reader.path(_require_node_id(kwargs, "from_id"), _require_node_id(kwargs, "to_id"))
        if operation == "blast_radius":
            return reader.blast_radius(_require_node_id(kwargs, "node_id"), _require_int(kwargs, "depth"))
        if operation == "conflicts":
            return reader.conflicts(_require_str(kwargs, "scope"))
        if operation == "load":
            return reader.load(_require_node_id(kwargs, "person_id"), _require_window(kwargs))
        if operation == "series":
            return reader.series(_require_node_id(kwargs, "commitment_id"))
        if operation == "history":
            return reader.history(_require_node_id(kwargs, "entity_id"))
        if operation == "decisions_touching":
            return reader.decisions_touching(_require_node_id(kwargs, "entity_id"))
        if operation == "concession_ledger":
            return reader.concession_ledger(_require_node_id(kwargs, "person_id"))
        if operation == "unexplained":
            return reader.unexplained(_require_str(kwargs, "scope"))
        if operation == "unverified":
            return reader.unverified(_require_str(kwargs, "scope"))
        if operation == "expected_but_absent":
            return reader.expected_but_absent(_require_node_id(kwargs, "constraint_id"))
        if operation == "spend_by_category":
            return reader.spend_by_category(_require_window(kwargs))
        if operation == "effort_evidence":
            return reader.effort_evidence(_require_node_id(kwargs, "person_id"), _require_window(kwargs))
        raise AssertionError(  # pragma: no cover
            f"unreachable: operation {operation!r} passed validation but has no dispatch"
        )


def _missing_arg(key: str) -> ToolFailure:
    return ToolFailure(
        tool_name="graph_reader", reason=f"missing/invalid required arg '{key}'", retryable=False
    )


def _require_node_id(kwargs: dict[str, object], key: str) -> NodeId:
    value = kwargs.get(key)
    if not isinstance(value, str):
        raise _missing_arg(key)
    return NodeId(value)


def _require_edge_type(kwargs: dict[str, object], key: str) -> EdgeType:
    value = kwargs.get(key)
    if isinstance(value, EdgeType):
        return value
    if isinstance(value, str):
        try:
            return EdgeType(value)
        except ValueError as exc:
            raise ToolFailure(
                tool_name="graph_reader", reason=f"invalid edge_type {value!r}", retryable=False
            ) from exc
    raise _missing_arg(key)


def _require_str(kwargs: dict[str, object], key: str) -> str:
    value = kwargs.get(key)
    if not isinstance(value, str):
        raise _missing_arg(key)
    return value


def _require_int(kwargs: dict[str, object], key: str) -> int:
    value = kwargs.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _missing_arg(key)
    return value


def _require_window(kwargs: dict[str, object]) -> tuple[datetime, datetime]:
    value = kwargs.get("window")
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not isinstance(value[0], datetime)
        or not isinstance(value[1], datetime)
    ):
        raise _missing_arg("window")
    return (value[0], value[1])


__all__ = ["GraphReadTool"]

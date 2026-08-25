"""`GraphWriteTool` — the concrete T3 tool: a provenance-enforcing,
idempotency-keyed wrapper around `contracts.repositories.GraphWriter`
(Phase 5 task item 1).

Two safety properties, both structural rather than conventions:

- **Provenance-enforcing**: this tool adds no provenance logic of its own
  — it delegates every write to the real `GraphWriter`
  (`app.graph.writer.FirestoreGraphWriter`, Phase 1), whose own guard
  (`app.persistence.provenance_guard.validate_provenance`) rejects any
  node/edge with incomplete provenance *before* any network write. That
  guard is safety invariant #3's enforcement point; this tool inherits it
  by construction rather than re-implementing it.
- **Idempotency-keyed**: spec §19.1 — T3+ tools carry an idempotency key;
  replays are no-ops returning the original result. `invoke_idempotent` is
  the *only* entry point this class exposes (there is no bare `invoke`) —
  a caller cannot accidentally bypass idempotency by calling the "wrong"
  method, because the "wrong" method does not exist.
"""

from __future__ import annotations

from contracts.actions import ActionResult
from contracts.errors import ProvenanceMissing, ToolFailure
from contracts.graph_types import Edge, NodeId
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import IdempotentTool, PermissionTier

_OPERATIONS = ("write_node", "write_edge", "supersede_node")


class GraphWriteTool(IdempotentTool):
    """Structurally satisfies `contracts.tools.IdempotentTool`. Writer
    agents only, per spec §16.1's T3 row — this tool performs no
    permission check of its own (that is `ToolRegistry`'s job at
    registration time); it is the *effect*, not the gate.
    """

    def __init__(
        self,
        *,
        graph_writer: GraphWriter,
        idempotency_store: IdempotencyStore,
        name: str = "graph_writer",
    ) -> None:
        self.name = name
        self.tier: PermissionTier = PermissionTier.T3_INTERNAL_WRITE
        self._writer = graph_writer
        self._idempotency_store = idempotency_store

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Performs one `write_node` / `write_edge` / `supersede_node` call,
        exactly once per `idempotency_key`.

        Args:
            idempotency_key: `contracts.actions.IdempotencyKey.as_str()`.
            operation: one of `_OPERATIONS`.
            node: the node to write (`operation="write_node"`).
            edge: the `Edge` to write (`operation="write_edge"`).
            old_node_id` / `new_node`: for `operation="supersede_node"`.

        Returns:
            `ActionResult.success(result_id)` — `result_id` is the written
            `NodeId` for `write_node`/`supersede_node`, or the edge's own
            `EdgeId` (as a plain `str`) for `write_edge`. On replay (a
            second call with the same `idempotency_key`), returns the
            *original* call's result without invoking `GraphWriter` again.

        Raises:
            contracts.errors.ProvenanceMissing: propagates unchanged — a
                structural safety-invariant violation, never reclassified
                as an ordinary `ToolFailure`.
            contracts.errors.ToolFailure: any other underlying failure
                (e.g. a Firestore connectivity error, an unknown
                `operation`). Never swallowed, never reinterpreted as a
                success (safety invariant #7).
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(cached_result_ref)

        operation = kwargs.get("operation")
        if operation not in _OPERATIONS:
            raise ToolFailure(
                tool_name=self.name,
                reason=f"unknown or missing operation {operation!r}; expected one of {_OPERATIONS}",
                retryable=False,
            )

        try:
            result_ref = self._perform(operation, kwargs)
        except ProvenanceMissing:
            # A structural safety-invariant violation, not an operational
            # tool failure — never reclassified, never recorded as a
            # completed idempotency result (the key stays "reserved", safe
            # to retry once the caller fixes the provenance).
            raise
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, see graph_read_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        self._idempotency_store.record_result(idempotency_key, result_ref)
        return ActionResult.success(result_ref)

    def _perform(self, operation: str, kwargs: dict[str, object]) -> str:
        if operation == "write_node":
            node_id = self._writer.write_node(kwargs.get("node"))
            return str(node_id)
        if operation == "write_edge":
            edge = kwargs.get("edge")
            if not isinstance(edge, Edge):
                raise ToolFailure(
                    tool_name=self.name, reason="'edge' must be a contracts.graph_types.Edge", retryable=False
                )
            self._writer.write_edge(edge)
            return str(edge.id)
        if operation == "supersede_node":
            old_node_id = kwargs.get("old_node_id")
            if not isinstance(old_node_id, str):
                raise ToolFailure(
                    tool_name=self.name, reason="missing/invalid 'old_node_id'", retryable=False
                )
            new_node_id = self._writer.supersede_node(NodeId(old_node_id), kwargs.get("new_node"))
            return str(new_node_id)
        raise AssertionError(  # pragma: no cover
            f"unreachable: operation {operation!r} passed validation but has no dispatch"
        )


__all__ = ["GraphWriteTool"]

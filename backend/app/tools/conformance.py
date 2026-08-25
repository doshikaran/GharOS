"""Structural protocol conformance for `backend/app/tools/`, enforced by
`mypy --strict` — mirrors `app.graph.conformance` / `app.persistence.
conformance` / `app.audit.conformance`'s established pattern (see
`app.persistence.conformance`'s docstring for the full rationale).
"""

from __future__ import annotations

from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import IdempotentTool, ReadOnlyTool, Tool

from app.tools.graph_read_tool import GraphReadTool
from app.tools.graph_write_tool import GraphWriteTool


def _graph_read_tool_conforms_to_tool(reader: GraphReader) -> Tool:
    return GraphReadTool(graph_reader=reader)


def _graph_read_tool_conforms_to_read_only_tool(reader: GraphReader) -> ReadOnlyTool:
    return GraphReadTool(graph_reader=reader)


def _graph_write_tool_conforms(writer: GraphWriter, idempotency_store: IdempotencyStore) -> IdempotentTool:
    return GraphWriteTool(graph_writer=writer, idempotency_store=idempotency_store)


__all__ = [
    "_graph_read_tool_conforms_to_read_only_tool",
    "_graph_read_tool_conforms_to_tool",
    "_graph_write_tool_conforms",
]

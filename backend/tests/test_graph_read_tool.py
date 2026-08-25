"""Tests for `app.tools.graph_read_tool.GraphReadTool` — the concrete T0
tool wrapping `contracts.repositories.GraphReader`.
"""

from __future__ import annotations

import pytest
from contracts.errors import ToolFailure
from contracts.graph_types import EdgeType, NodeId, Person
from contracts.tools import PermissionTier

from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.tools.graph_read_tool import GraphReadTool
from tests.conftest import make_person


class TestGraphReadToolDispatch:
    def test_tier_is_t0(self, reader: FirestoreGraphReader) -> None:
        tool = GraphReadTool(graph_reader=reader)
        assert tool.tier is PermissionTier.T0_READ
        assert tool.name == "graph_reader"

    def test_get_node_dispatches_to_reader(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(make_person("person-1", "Priya"))
        tool = GraphReadTool(graph_reader=reader)

        result = tool.invoke(operation="get_node", node_id="person-1")

        assert result.ok is True
        value = result.value
        assert isinstance(value, Person)
        assert value.display_name == "Priya"

    def test_neighbours_dispatches_to_reader(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(make_person("person-1", "Priya"))
        tool = GraphReadTool(graph_reader=reader)

        result = tool.invoke(operation="neighbours", node_id="person-1", edge_type=EdgeType.OWNED_BY)

        assert result.ok is True
        assert result.value == ()

    def test_conflicts_dispatches_to_reader(self, reader: FirestoreGraphReader) -> None:
        tool = GraphReadTool(graph_reader=reader)
        result = tool.invoke(operation="conflicts", scope="all")
        assert result.ok is True
        assert result.value == ()


class TestGraphReadToolFailureNeverFabricatesSuccess:
    def test_unknown_operation_raises_tool_failure(self, reader: FirestoreGraphReader) -> None:
        tool = GraphReadTool(graph_reader=reader)
        with pytest.raises(ToolFailure) as exc_info:
            tool.invoke(operation="not_a_real_operation")
        assert exc_info.value.tool_name == "graph_reader"

    def test_missing_operation_raises_tool_failure(self, reader: FirestoreGraphReader) -> None:
        tool = GraphReadTool(graph_reader=reader)
        with pytest.raises(ToolFailure):
            tool.invoke(node_id="person-1")

    def test_missing_required_arg_raises_tool_failure_not_a_bare_exception(
        self, reader: FirestoreGraphReader
    ) -> None:
        tool = GraphReadTool(graph_reader=reader)
        with pytest.raises(ToolFailure):
            tool.invoke(operation="get_node")  # no node_id

    def test_underlying_reader_failure_surfaces_as_tool_failure(self) -> None:
        """Adversarial: force the underlying `GraphReader` to raise on a
        genuine failure (e.g. a broken connection) and assert it never
        becomes an `ActionResult.success` — safety invariant #7."""

        class _BrokenReader:
            def get_node(self, node_id: NodeId) -> object | None:
                raise RuntimeError("simulated Firestore connectivity failure")

        tool = GraphReadTool(graph_reader=_BrokenReader())  # type: ignore[arg-type]
        with pytest.raises(ToolFailure) as exc_info:
            tool.invoke(operation="get_node", node_id="person-1")
        assert "simulated Firestore connectivity failure" in exc_info.value.reason
        assert exc_info.value.retryable is True

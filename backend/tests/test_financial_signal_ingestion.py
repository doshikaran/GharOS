"""Tests for `app.adapters.financial_signal_ingestion.FinancialSignalIngestor`
(A27) — cross-channel dedup, idempotent-replay-safety, and edge-write
gating, run against the real Firestore emulator (`conftest.py`'s `writer`/
`idempotency_store` fixtures), matching the rigor established by
`test_graph_write_tool.py`'s `TestForcedReplayNeverDoubleExecutes`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    GraphMappingResult,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Provenance,
    SourceRef,
)

from app.adapters.financial_signal_ingestion import FinancialSignalIngestor
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.tools.graph_write_tool import GraphWriteTool

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _CountingGraphWriter:
    """Spy around a real `FirestoreGraphWriter` — call-count proof that the
    underlying effect never runs twice, mirroring `test_graph_write_tool.py`'s
    `_CountingGraphWriter`."""

    def __init__(self, real: FirestoreGraphWriter) -> None:
        self._real = real
        self.write_node_calls = 0
        self.write_edge_calls = 0

    def write_node(self, node: Any) -> NodeId:
        self.write_node_calls += 1
        return self._real.write_node(node)

    def write_edge(self, edge: Any) -> None:
        self.write_edge_calls += 1
        self._real.write_edge(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        return self._real.supersede_node(old_node_id, new_node)


def _prov(*, source_document_id: str, region: str, confidence: float = 0.9) -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId(source_document_id), region=region),
        confidence=confidence,
        deriving_agent=AgentId("A3"),
        created_at=NOW,
    )


def _event(
    *,
    node_id: str,
    source_document_id: str,
    region: str,
    kind: LedgerEventKind = LedgerEventKind.DEBIT,
    amount: float = 499.0,
    currency: str = "INR",
    occurred_at: datetime = NOW,
    counterparty_raw: str = "Netflix India",
) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(node_id),
        provenance=_prov(source_document_id=source_document_id, region=region),
        kind=kind,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        counterparty_raw=counterparty_raw,
    )


def _mapping(*events_and_edges: LedgerEvent | tuple[LedgerEvent, tuple[Edge, ...]]) -> GraphMappingResult:
    nodes: list[object] = []
    edges: list[Edge] = []
    for item in events_and_edges:
        if isinstance(item, tuple):
            event, event_edges = item
            nodes.append(event)
            edges.extend(event_edges)
        else:
            nodes.append(item)
    return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


def _ingestor(
    spy: _CountingGraphWriter, idempotency_store: FirestoreIdempotencyStore
) -> FinancialSignalIngestor:
    tool = GraphWriteTool(graph_writer=spy, idempotency_store=idempotency_store)
    return FinancialSignalIngestor(graph_write_tool=tool)


class TestNewEventIsWrittenOnce:
    def test_single_candidate_written(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)
        event = _event(node_id="ledger-1", source_document_id="doc-sms-1", region="body")

        outcomes = ingestor.ingest(mapping_results=(_mapping(event),))

        assert len(outcomes) == 1
        assert outcomes[0].action == "written"
        assert spy.write_node_calls == 1


class TestCrossChannelDeduplication:
    def test_same_transaction_from_two_channels_is_deduplicated(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)

        sms_event = _event(
            node_id="ledger-sms",
            source_document_id="doc-sms-1",
            region="body",
            amount=499.0,
            counterparty_raw="NETFLIX",
            occurred_at=NOW,
        )
        statement_event = _event(
            node_id="ledger-stmt",
            source_document_id="doc-statement-1",
            region="row-12",
            amount=499.0,
            counterparty_raw="NETFLIX ENTERTAINMENT",
            occurred_at=NOW + timedelta(days=2),
        )

        outcomes = ingestor.ingest(mapping_results=(_mapping(sms_event), _mapping(statement_event)))

        assert [o.action for o in outcomes] == ["written", "deduplicated"]
        assert outcomes[1].node_id == outcomes[0].node_id
        assert spy.write_node_calls == 1, "the second channel's report of the same debit must not be written"

    def test_genuinely_different_transactions_are_both_written(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)

        first = _event(node_id="ledger-a", source_document_id="doc-a", region="r1", amount=499.0)
        second = _event(node_id="ledger-b", source_document_id="doc-b", region="r1", amount=1299.0)

        outcomes = ingestor.ingest(mapping_results=(_mapping(first, second),))

        assert [o.action for o in outcomes] == ["written", "written"]
        assert spy.write_node_calls == 2

    def test_dedup_checks_against_caller_supplied_existing_events(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)
        already_in_graph = _event(
            node_id="ledger-existing", source_document_id="doc-old", region="r1", amount=499.0
        )
        new_report = _event(node_id="ledger-new", source_document_id="doc-new", region="r1", amount=499.0)

        outcomes = ingestor.ingest(
            mapping_results=(_mapping(new_report),), existing_events=(already_in_graph,)
        )

        assert outcomes[0].action == "deduplicated"
        assert outcomes[0].node_id == already_in_graph.id
        assert spy.write_node_calls == 0


class TestReplaySafety:
    def test_reingesting_the_same_document_never_double_writes(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        """ "Kill a run mid-flight, restart" (spec §19.1) applied to A27: the
        same document (same source_document_id + region) processed twice —
        e.g. a retried Pub/Sub delivery — must write its LedgerEvent
        exactly once."""
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)
        event = _event(node_id="ledger-replay", source_document_id="doc-replay-1", region="body")

        first = ingestor.ingest(mapping_results=(_mapping(event),))
        second = ingestor.ingest(mapping_results=(_mapping(event),))

        assert first[0].node_id == second[0].node_id
        assert spy.write_node_calls == 1, "re-processing the same document must not write a second node"


class TestEdgesWrittenOnlyForWrittenNodes:
    def test_edge_written_alongside_new_node(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)
        event = _event(node_id="ledger-with-edge", source_document_id="doc-1", region="r1")
        edge = Edge(
            id=EdgeId("edge-1"),
            provenance=event.provenance,
            edge_type=EdgeType.OWED_TO,
            from_id=event.id,
            to_id=NodeId("vendor:netflix-india"),
        )

        ingestor.ingest(mapping_results=(_mapping((event, (edge,))),))

        assert spy.write_edge_calls == 1

    def test_edge_not_written_for_a_deduplicated_node(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        spy = _CountingGraphWriter(writer)
        ingestor = _ingestor(spy, idempotency_store)
        first_event = _event(node_id="ledger-first", source_document_id="doc-1", region="r1", amount=499.0)
        dup_event = _event(node_id="ledger-dup", source_document_id="doc-2", region="r1", amount=499.0)
        dup_edge = Edge(
            id=EdgeId("edge-dup"),
            provenance=dup_event.provenance,
            edge_type=EdgeType.OWED_TO,
            from_id=dup_event.id,
            to_id=NodeId("vendor:netflix-india"),
        )

        ingestor.ingest(mapping_results=(_mapping(first_event), _mapping((dup_event, (dup_edge,)))))

        assert spy.write_edge_calls == 0, "a deduplicated event's edges must not be written either"


class TestModuleHoldsNoActionCapability:
    def test_module_imports_no_gated_tool_machinery(self) -> None:
        """Structural proof of A27's own forbidden list ('action') — this
        module has no importable path to a T4/T5/T6 tool at all, mirroring
        `test_action_construction_boundary.py`'s established AST-based
        style rather than a mere docstring claim."""
        import ast
        from pathlib import Path

        module_path = (
            Path(__file__).resolve().parent.parent / "app" / "adapters" / "financial_signal_ingestion.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_names.append(node.module)
        forbidden = ("app.arbitration", "contracts.tools")
        violations = [name for name in imported_names if any(f in name for f in forbidden)]
        assert violations == [], f"A27 must hold no action capability, found imports: {violations}"

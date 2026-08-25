"""Tests for `app.arbitration.executor.ActionExecutor` — the R0/R1 half of
"the only path to action" (spec §15.12), run against the real Firestore
emulator (audit log + graph writer + idempotency store).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import AgentId, NodeId, Person

from app.arbitration.errors import ArbiterDecisionNotExecutable
from app.arbitration.executor import ActionExecutor
from app.arbitration.types import ArbiterDecision, ArbiterResult, ProposedAction
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.tools.graph_write_tool import GraphWriteTool
from tests.conftest import make_person

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _execute_result(action_type: str = "graph_write") -> ArbiterResult:
    proposed = ProposedAction(
        action_type=action_type,
        entity_id="person-1",
        cycle="2026-08",
        target_node_id=NodeId("person-1"),
        confidence=0.95,
        involves_hard_constraint=False,
        reasoning="Routine graph write.",
        evidence_consulted=(),
        consequence_if_wrong="Minor, superseded on correction.",
        proposed_by=AgentId("A15"),
        source_ref=None,
    )
    return ArbiterResult(
        proposed_action=proposed,
        decision=ArbiterDecision.EXECUTE,
        final_risk_tier=RiskTier.R0_SILENT,
        confidence=0.95,
        evidence_bundle=EvidenceBundle("write", "reasoning", (), 0.95, "minor"),
        escalated_to_pro=False,
    )


class TestActionExecutorRunsTheGraphWrite:
    def test_execute_writes_the_node_and_audits_before_execute(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = GraphWriteTool(graph_writer=writer, idempotency_store=idempotency_store)
        executor = ActionExecutor(tool=tool, audit_log=audit_log)

        result = executor.execute(
            _execute_result(),
            invoke_kwargs={"operation": "write_node", "node": make_person("person-1", "Priya")},
        )

        assert result.ok is True
        stored = reader.get_node(NodeId("person-1"))
        assert isinstance(stored, Person)
        assert stored.display_name == "Priya"

        matching = [r for r in audit_log.all_records() if r.payload.get("entity_id") == "person-1"]
        assert len(matching) == 1

    def test_non_execute_decision_is_rejected(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = GraphWriteTool(graph_writer=writer, idempotency_store=idempotency_store)
        executor = ActionExecutor(tool=tool, audit_log=audit_log)
        approve_result = ArbiterResult(
            proposed_action=_execute_result().proposed_action,
            decision=ArbiterDecision.APPROVE,
            final_risk_tier=RiskTier.R2_APPROVE,
            confidence=0.95,
            evidence_bundle=EvidenceBundle("x", "y", (), 0.95, "z"),
            escalated_to_pro=False,
        )
        with pytest.raises(ArbiterDecisionNotExecutable):
            executor.execute(approve_result, invoke_kwargs={})

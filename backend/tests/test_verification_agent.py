"""Tests for A3c Verification Agent (`app.agents.intake.verification_agent`).

spec §15.2 A3c / §5.5: given a verification document (a receipt),
judge `verifies`/`contradicts`/`absent_from` against the existing graph.
Pro-tier. **Forbidden: silently overwriting a contradicted graph claim —
always opens a discrepancy and escalates.**

Runs against the real Firestore emulator (`reader`/`writer` fixtures from
`conftest.py`) rather than a hand-rolled fake `GraphReader` — matches this
repo's established "integration tests against the actual emulator, not
mocks" convention (gharos-standards) and lets this suite prove the
**"never silently overwrite"** rule against real, persisted prior edges,
not a mocked return value.

**Gate 3 planted case, satisfied here:**
`test_contradicting_verdict_opens_discrepancy_never_overwrites_prior_edge`
— a receipt disagrees with an existing `verifies` edge on a nut-free
constraint; the prior edge is proven to still be readable afterwards.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
    PurchaseItem,
    SourceRef,
)

from app.agents.intake.verification_agent import VerificationAgent
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _provenance(confidence: float = 0.9) -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("prior-receipt"), region="0-10"),
        confidence=confidence,
        deriving_agent=AgentId("A3"),
        created_at=_NOW,
    )


def _purchase_item(node_id: str, description: str, category: str | None) -> PurchaseItem:
    return PurchaseItem(
        id=NodeId(node_id),
        provenance=_provenance(),
        ledger_event_id=NodeId("ledger-1"),
        description=description,
        normalized_category=category,
        quantity=1.0,
        unit_price=100.0,
        line_total=100.0,
    )


def _nut_free_constraint(writer: FirestoreGraphWriter) -> Constraint:
    constraint = Constraint(
        id=NodeId("constraint-nut-free"),
        provenance=_provenance(),
        kind=ConstraintKind.DIETARY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={"allergen": "nut"},
        original_text="Aarav must never be given anything containing nuts.",
    )
    writer.write_node(constraint)
    return constraint


def _agent(gemini_response: dict[str, object], *, reader: FirestoreGraphReader) -> VerificationAgent:
    fake_models = FakeModels(texts=[json.dumps(gemini_response)])
    client = GeminiClient(router=fake_router(fake_models))
    return VerificationAgent(gemini_client=client, graph_reader=reader)


class TestVerifiesAndContradicts:
    def test_verifying_purchase_produces_verifies_edge(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        constraint = _nut_free_constraint(writer)
        safe_item = _purchase_item("item-safe-bread", "Nut-free bread", "bakery")

        agent = _agent(
            {
                "judgments": [
                    {
                        "constraint_id": str(constraint.id),
                        "verdict": "verifies",
                        "matched_item_description": "Nut-free bread",
                        "reasoning": "The bread is explicitly labelled nut-free.",
                        "confidence": 0.9,
                    }
                ]
            },
            reader=reader,
        )
        result = agent.verify_against_constraints(
            source_document_id=NodeId("receipt-1"),
            purchase_items=(safe_item,),
            candidate_constraints=(constraint,),
        )

        assert len(result.edges) == 1
        assert result.edges[0].edge_type is EdgeType.VERIFIES
        assert result.edges[0].from_id == safe_item.id
        assert result.edges[0].to_id == constraint.id
        assert result.edges[0].provenance.derivation is Derivation.INFERRED
        assert result.discrepancies == ()
        assert result.agent_output.model_tier is ModelTier.PRO

    def test_contradicting_verdict_opens_discrepancy_never_overwrites_prior_edge(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        """The Gate 3 planted mismatch case."""
        constraint = _nut_free_constraint(writer)

        # A prior receipt already verified this constraint was honoured.
        prior_item = _purchase_item("item-prior-verified", "Nut-free bread (prior week)", "bakery")
        writer.write_node(prior_item)
        prior_item_id = prior_item.id
        prior_edge = Edge(
            id=EdgeId("edge-prior-verifies"),
            provenance=_provenance(),
            edge_type=EdgeType.VERIFIES,
            from_id=prior_item_id,
            to_id=constraint.id,
        )
        writer.write_edge(prior_edge)
        assert reader.neighbours(constraint.id, EdgeType.VERIFIES) != ()

        # New receipt disagrees: it shows a peanut-containing item.
        violating_item = _purchase_item("item-peanut-butter", "Peanut butter jar", "pantry")
        agent = _agent(
            {
                "judgments": [
                    {
                        "constraint_id": str(constraint.id),
                        "verdict": "contradicts",
                        "matched_item_description": "Peanut butter jar",
                        "reasoning": "Peanut butter directly contains the allergen the constraint forbids.",
                        "confidence": 0.95,
                    }
                ]
            },
            reader=reader,
        )
        result = agent.verify_against_constraints(
            source_document_id=NodeId("receipt-2"),
            purchase_items=(violating_item,),
            candidate_constraints=(constraint,),
        )

        # A new CONTRADICTS edge is proposed...
        assert len(result.edges) == 1
        assert result.edges[0].edge_type is EdgeType.CONTRADICTS
        # ...and a discrepancy is opened because it disagrees with the
        # prior VERIFIES edge already in the graph.
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].constraint_id == constraint.id
        assert result.discrepancies[0].conflicting_prior_edge_type is EdgeType.VERIFIES

        # Critically: A3c never had write access at all (no GraphWriter
        # dependency) — the prior edge is untouched, still readable.
        assert reader.neighbours(constraint.id, EdgeType.VERIFIES) != ()

    def test_unrelated_verdict_produces_no_edge(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        constraint = _nut_free_constraint(writer)
        unrelated_item = _purchase_item("item-detergent", "Laundry detergent", "household")
        agent = _agent(
            {
                "judgments": [
                    {
                        "constraint_id": str(constraint.id),
                        "verdict": "unrelated",
                        "matched_item_description": None,
                        "reasoning": "Detergent has nothing to do with a nut allergy.",
                        "confidence": 0.95,
                    }
                ]
            },
            reader=reader,
        )
        result = agent.verify_against_constraints(
            source_document_id=NodeId("receipt-3"),
            purchase_items=(unrelated_item,),
            candidate_constraints=(constraint,),
        )
        assert result.edges == ()
        assert result.discrepancies == ()


class TestAbsentFrom:
    def test_expected_category_never_purchased_produces_absent_from_finding(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        constraint = Constraint(
            id=NodeId("constraint-weekly-bread"),
            provenance=_provenance(),
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.SOFT,
            validity_start=None,
            validity_end=None,
            structured={"expected_category": "bakery"},
            original_text="We always buy nut-free bread weekly.",
        )
        writer.write_node(constraint)

        other_item = _purchase_item("item-milk", "Milk 1 litre", "dairy_and_milk")
        agent = _agent({"judgments": []}, reader=reader)
        result = agent.verify_against_constraints(
            source_document_id=NodeId("receipt-4"),
            purchase_items=(other_item,),
            candidate_constraints=(constraint,),
        )

        assert len(result.absent_from_findings) == 1
        assert result.absent_from_findings[0].constraint_id == constraint.id
        assert result.absent_from_findings[0].expected_category == "bakery"

    def test_expected_category_present_produces_no_finding(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        constraint = Constraint(
            id=NodeId("constraint-weekly-bread-2"),
            provenance=_provenance(),
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.SOFT,
            validity_start=None,
            validity_end=None,
            structured={"expected_category": "bakery"},
            original_text="We always buy nut-free bread weekly.",
        )
        writer.write_node(constraint)

        bread_item = _purchase_item("item-bread", "Nut-free bread", "bakery")
        agent = _agent({"judgments": []}, reader=reader)
        result = agent.verify_against_constraints(
            source_document_id=NodeId("receipt-5"),
            purchase_items=(bread_item,),
            candidate_constraints=(constraint,),
        )
        assert result.absent_from_findings == ()

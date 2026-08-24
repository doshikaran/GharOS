"""Tests for A15 Obligation Writer (`app.agents.consequence.obligation_writer`).

PHASES.md Gate 4: "Cross-channel duplicate deduplicates; genuine
follow-up supersedes rather than duplicating." Real Firestore emulator
throughout (`reader`/`writer` fixtures) — this agent's whole job is
writing to the graph, so mocking it out would test nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from contracts.agents import Citation
from contracts.graph_types import (
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
)

from app.agents.consequence.errors import CandidateDependencyCycle
from app.agents.consequence.obligation_writer import ObligationWriter
from app.agents.consequence.types import HouseholdContext, ImpliedObligationCandidate
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from tests.conftest import NOW

_EMPTY_CONTEXT = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())


def _get_obligation(reader: FirestoreGraphReader, node_id: NodeId | None) -> Obligation:
    assert node_id is not None
    node = reader.get_node(node_id)
    assert isinstance(node, Obligation)
    return node


def _candidate(
    candidate_id: str,
    title: str,
    *,
    obligation_type: str = "errand",
    due_at: datetime | None = None,
    effort_estimate_minutes: int | None = 15,
    confidence: float = 0.85,
    depends_on: tuple[str, ...] = (),
) -> ImpliedObligationCandidate:
    return ImpliedObligationCandidate(
        candidate_id=candidate_id,
        title=title,
        obligation_type=obligation_type,
        due_at=due_at,
        effort_estimate_minutes=effort_estimate_minutes,
        reasoning="test reasoning",
        citation=Citation(source_document_id="doc-writer-1", region="0-5", supports_claim=title),
        cited_span_text="stub",
        confidence=confidence,
        depends_on_candidate_ids=depends_on,
    )


class TestNewObligationWritten:
    def test_writes_a_new_obligation_with_full_provenance(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        candidate = _candidate("cand-new-1", "Sign the permission slip", obligation_type="permission_slip")

        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-1"),
            candidates=(candidate,),
            household_context=_EMPTY_CONTEXT,
        )

        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.action == "written"
        assert outcome.node_id is not None

        written = _get_obligation(reader, outcome.node_id)
        assert written.title == "Sign the permission slip"
        assert written.stated_or_implied is ObligationDerivation.IMPLIED
        assert written.status is ObligationStatus.DERIVED
        assert written.provenance.deriving_agent == "A12"

        implied_nodes = reader.neighbours(NodeId("doc-writer-1"), EdgeType.IMPLIES)
        assert any(getattr(node, "id", None) == outcome.node_id for node in implied_nodes)


class TestCrossChannelDeduplication:
    def test_same_fact_restated_deduplicates_not_written_again(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)

        first = _candidate(
            "cand-dup-first", "Pay the ₹500 field trip fee", obligation_type="payment", due_at=NOW
        )
        first_outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-email"),
            candidates=(first,),
            household_context=_EMPTY_CONTEXT,
        )
        existing_node = _get_obligation(reader, first_outcomes[0].node_id)

        context_with_existing = HouseholdContext(
            people=(), constraints=(), open_obligations=(existing_node,), stated_obligations=()
        )
        second = _candidate(
            "cand-dup-second",
            "Pay the ₹500 field trip fee",
            obligation_type="payment",
            due_at=NOW + timedelta(minutes=10),  # within tolerance
        )
        second_outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-whatsapp"),
            candidates=(second,),
            household_context=context_with_existing,
        )

        assert len(second_outcomes) == 1
        assert second_outcomes[0].action == "deduplicated"
        assert second_outcomes[0].node_id == first_outcomes[0].node_id


class TestGenuineFollowUpSupersedes:
    def test_materially_changed_obligation_supersedes_the_old_one(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)

        original = _candidate(
            "cand-super-original",
            "Pay the ₹500 field trip fee",
            obligation_type="payment",
            due_at=NOW,
        )
        original_outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-original"),
            candidates=(original,),
            household_context=_EMPTY_CONTEXT,
        )
        existing_node = _get_obligation(reader, original_outcomes[0].node_id)

        context_with_existing = HouseholdContext(
            people=(), constraints=(), open_obligations=(existing_node,), stated_obligations=()
        )
        follow_up = _candidate(
            "cand-super-followup",
            "Pay the ₹600 field trip fee",  # amount changed -> genuine update
            obligation_type="payment",
            due_at=NOW + timedelta(days=2),  # due date moved well beyond tolerance
        )
        follow_up_outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-followup"),
            candidates=(follow_up,),
            household_context=context_with_existing,
        )

        assert len(follow_up_outcomes) == 1
        outcome = follow_up_outcomes[0]
        assert outcome.action == "superseded"
        assert outcome.node_id != existing_node.id
        assert outcome.node_id is not None

        supersedes_edges = reader.neighbours(outcome.node_id, EdgeType.SUPERSEDES)
        assert any(getattr(node, "id", None) == existing_node.id for node in supersedes_edges)

        old_current = _get_obligation(reader, existing_node.id)
        assert old_current.provenance.superseded_at is not None


class TestMustStartByComputation:
    def test_no_dependencies_uses_own_due_at_minus_effort(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        due = NOW + timedelta(days=1)
        candidate = _candidate("cand-msb-1", "Simple task", due_at=due, effort_estimate_minutes=30)

        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-msb"),
            candidates=(candidate,),
            household_context=_EMPTY_CONTEXT,
        )
        written = _get_obligation(reader, outcomes[0].node_id)
        assert written.must_start_by == due - timedelta(minutes=30)

    def test_dependency_chain_tightens_must_start_by(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        """A dependent candidate's `must_start_by` is bounded by the
        earliest due date anywhere in its dependency chain, not just its
        own due date — the field-trip case: the slip's own due date is
        Wednesday, but a prerequisite step due Monday should tighten it."""
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)

        prerequisite = _candidate(
            "cand-msb-prereq",
            "Find the permission slip form",
            due_at=NOW + timedelta(days=1),
            effort_estimate_minutes=0,
        )
        dependent = _candidate(
            "cand-msb-dependent",
            "Sign and return the permission slip",
            due_at=NOW + timedelta(days=3),
            effort_estimate_minutes=10,
            depends_on=("cand-msb-prereq",),
        )

        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-msb-chain"),
            candidates=(prerequisite, dependent),
            household_context=_EMPTY_CONTEXT,
        )
        outcome_by_id = {o.candidate_id: o for o in outcomes}
        dependent_node = _get_obligation(reader, outcome_by_id["cand-msb-dependent"].node_id)
        # earliest due date in the chain is the prerequisite's (NOW + 1 day),
        # not the dependent's own (NOW + 3 days)
        assert dependent_node.must_start_by == (NOW + timedelta(days=1)) - timedelta(minutes=10)

    def test_no_due_at_anywhere_leaves_must_start_by_none(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        candidate = _candidate("cand-msb-none", "Undated task", due_at=None, effort_estimate_minutes=10)
        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-msb-none"),
            candidates=(candidate,),
            household_context=_EMPTY_CONTEXT,
        )
        written = _get_obligation(reader, outcomes[0].node_id)
        assert written.must_start_by is None


class TestDependsOnEdgesWritten:
    def test_dependent_candidate_gets_a_depends_on_edge_to_its_prerequisite(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        prerequisite = _candidate("cand-dep-prereq", "Buy stamps")
        dependent = _candidate("cand-dep-dependent", "Mail the form", depends_on=("cand-dep-prereq",))

        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-deps"),
            candidates=(prerequisite, dependent),
            household_context=_EMPTY_CONTEXT,
        )
        outcome_by_id = {o.candidate_id: o for o in outcomes}
        dependent_node_id = outcome_by_id["cand-dep-dependent"].node_id
        prerequisite_node_id = outcome_by_id["cand-dep-prereq"].node_id
        assert dependent_node_id is not None
        assert prerequisite_node_id is not None
        chain = reader.dependency_chain(dependent_node_id)
        assert prerequisite_node_id in {node.id for node in chain}


class TestCycleDetection:
    def test_cyclic_dependencies_within_a_batch_raise(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        a = _candidate("cand-cycle-a", "A", depends_on=("cand-cycle-b",))
        b = _candidate("cand-cycle-b", "B", depends_on=("cand-cycle-a",))

        with pytest.raises(CandidateDependencyCycle):
            obligation_writer.write(
                source_document_id=NodeId("doc-writer-cycle"),
                candidates=(a, b),
                household_context=_EMPTY_CONTEXT,
            )


class TestEmptyBatch:
    def test_empty_candidates_returns_empty_outcomes(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        obligation_writer = ObligationWriter(graph_reader=reader, graph_writer=writer)
        outcomes = obligation_writer.write(
            source_document_id=NodeId("doc-writer-empty"), candidates=(), household_context=_EMPTY_CONTEXT
        )
        assert outcomes == ()


class TestNoLLMCallEverHappens:
    def test_obligation_writer_has_no_gemini_client_dependency(self) -> None:
        """Structural proof this agent makes no LLM call at all — its
        `__init__` accepts only graph reader/writer, no `GeminiClient`."""
        import inspect

        signature = inspect.signature(ObligationWriter.__init__)
        assert "gemini_client" not in signature.parameters

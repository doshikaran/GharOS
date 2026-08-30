"""Phase 15 (E2) — the spec §24 live exception beat must fire identically
on every rehearsal and on camera.

The beat (per the Phase 15 dispatch and spec §26 "The verification pair"):
a grocery receipt flows through the intake -> verification path and A3c
surfaces the verification-receipt discrepancy —

  * a purchased item that **contradicts** the household nut-free HARD
    constraint (mixed nuts), opening a `Discrepancy` because a prior
    `verifies` edge already stands on that constraint, and
  * the **missing** nut-free item the constraint required, an
    `absent_from` finding.

The `absent_from` finding is the one signal that must be bit-exact every
run — spec §26: "producing an `absent_from` signal live on stage. This
single artifact demonstrates the loop closing." It is produced by
`VerificationAgent._check_absent_from`, deterministic code that never
reads model output. This module proves that: it runs the exact scenario
end-to-end (receipt fields -> `ReceiptExtractionStrategy` -> graph mapping
-> `VerificationAgent.verify_against_constraints`) many times over, first
with the model returning a *different, adversarial* judgment payload each
run, then with a stable payload (what `DETERMINISTIC_TEMPERATURE=0`
buys), and asserts the surfaced discrepancy is identical across every
run in both loops.

Runs against the real Firestore emulator (`reader`/`writer` fixtures) —
this repo's "integration tests against the actual emulator, not mocks"
convention, and the only way to prove the prior-`verifies`-edge lookup
that opens the `Discrepancy` behaves the same every time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    ExtractedField,
    NodeId,
    Provenance,
    PurchaseItem,
    SourceRef,
)

from app.agents.intake.line_item_extraction import LineItemExtraction
from app.agents.intake.strategies.receipt_strategy import ReceiptExtractionStrategy
from app.agents.intake.verification_agent import VerificationAgent
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_RUNS = 7  # >= 5, per the Phase 15 dispatch
_NOW = datetime(2026, 8, 30, tzinfo=UTC)
_A3 = AgentId("A3")
_RECEIPT_DOC = NodeId("doc-freshmart-receipt-demo")
_NUT_FREE = NodeId("constraint-nut-free-demo")


def _prov() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=_RECEIPT_DOC, region="0-10"),
        confidence=0.9,
        deriving_agent=_A3,
        created_at=_NOW,
    )


def _f(name: str, value: object) -> ExtractedField:
    return ExtractedField(
        name=name, value=value, confidence=0.9, source_region="0-10", derivation=Derivation.EXTRACTED
    )


def _line_item(description: str, category: str, region: str) -> LineItemExtraction:
    return LineItemExtraction(
        description=description,
        normalized_category=category,
        quantity=1.0,
        unit_price=100.0,
        line_total=100.0,
        tax=None,
        confidence=0.9,
        source_region=region,
        derivation=Derivation.EXTRACTED,
    )


# The engineered receipt: milk + mixed nuts (contradicts nut-free) +
# store-brand paneer. Deliberately NO bakery line -> the nut-free bread
# the constraint expects is absent.
_RECEIPT_FIELDS = (
    _f("merchant_name", "FreshMart"),
    _f("total", 300.0),
    _f("transaction_datetime", "2026-08-30T18:30:00"),
    _f(
        "line_items",
        (
            _line_item("Milk 1L", "dairy_and_milk", "line-1"),
            _line_item("Mixed nuts snack pack", "snacks", "line-7"),
            _line_item("Store-brand paneer 200g", "dairy_and_milk", "line-5"),
        ),
    ),
)


def _nut_free_constraint() -> Constraint:
    return Constraint(
        id=_NUT_FREE,
        provenance=_prov(),
        kind=ConstraintKind.DIETARY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        # `expected_category` is what makes the "missing nut-free item"
        # beat deterministic — `_check_absent_from` fires on it directly,
        # never via the model.
        structured={"allergen": "nut", "expected_category": "bakery"},
        original_text="Aarav is severely allergic to nuts — the nut-free bread must always be bought.",
    )


def _purchase_items() -> tuple[PurchaseItem, ...]:
    result = ReceiptExtractionStrategy().map_to_graph(
        source_document_id=_RECEIPT_DOC, extracted_fields=_RECEIPT_FIELDS, deriving_agent=_A3
    )
    return tuple(n for n in result.nodes if isinstance(n, PurchaseItem))


def _seed_prior_verifies_edge(writer: FirestoreGraphWriter, constraint: Constraint) -> None:
    """Last week the household DID buy the nut-free bread and A3c recorded
    a `verifies` edge. That prior edge is why this week's `contradicts`
    verdict must open a `Discrepancy` rather than silently flip the graph."""
    writer.write_node(constraint)
    prior_item = PurchaseItem(
        id=NodeId("item-prior-nut-free-bread"),
        provenance=_prov(),
        ledger_event_id=NodeId("ledger-prior"),
        description="Nut-free multigrain bread (last week)",
        normalized_category="bakery",
        quantity=1.0,
        unit_price=90.0,
        line_total=90.0,
    )
    writer.write_node(prior_item)
    writer.write_edge(
        Edge(
            id=EdgeId("edge-prior-verifies-demo"),
            provenance=_prov(),
            edge_type=EdgeType.VERIFIES,
            from_id=prior_item.id,
            to_id=constraint.id,
        )
    )


def _agent(reader: FirestoreGraphReader, judgments_json: str) -> VerificationAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=[judgments_json])))
    return VerificationAgent(gemini_client=client, graph_reader=reader)


# Seven DIFFERENT model payloads — reordered judgments, jittered
# confidences, an extra unrelated verdict, and one run of pure garbage.
# The `absent_from` beat must be identical regardless of any of this.
_ADVERSARIAL_PAYLOADS: tuple[str, ...] = (
    json.dumps(
        {
            "judgments": [
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "contradicts",
                    "matched_item_description": "Mixed nuts snack pack",
                    "reasoning": "Mixed nuts directly contain the forbidden allergen.",
                    "confidence": 0.95,
                }
            ]
        }
    ),
    json.dumps(
        {
            "judgments": [
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "contradicts",
                    "matched_item_description": "Mixed nuts snack pack",
                    "reasoning": "Contains nuts.",
                    "confidence": 0.61,
                },
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "unrelated",
                    "matched_item_description": "Milk 1L",
                    "reasoning": "Milk is irrelevant to a nut allergy.",
                    "confidence": 0.9,
                },
            ]
        }
    ),
    json.dumps(
        {
            "judgments": [
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "unrelated",
                    "matched_item_description": "Store-brand paneer 200g",
                    "reasoning": "Paneer has nothing to do with nuts.",
                    "confidence": 0.8,
                },
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "contradicts",
                    "matched_item_description": "Mixed nuts snack pack",
                    "reasoning": "Nut product under a nut-free constraint.",
                    "confidence": 0.99,
                },
            ]
        }
    ),
    json.dumps({"judgments": []}),  # model finds nothing to say
    json.dumps(
        {
            "judgments": [
                {
                    "constraint_id": "some-constraint-not-in-scope",
                    "verdict": "contradicts",
                    "matched_item_description": "Ghost item",
                    "reasoning": "References a constraint that was never passed in.",
                    "confidence": 0.9,
                }
            ]
        }
    ),
    json.dumps({"unexpected_key": "no judgments field at all", "judgments": []}),
    json.dumps(
        {
            "judgments": [
                {
                    "constraint_id": str(_NUT_FREE),
                    "verdict": "contradicts",
                    "matched_item_description": "Mixed nuts snack pack",
                    "reasoning": "   ",
                    "confidence": 0.72,
                }
            ]
        }
    ),
)


def _absent_from_fingerprint(agent: VerificationAgent, constraint: Constraint) -> tuple[tuple[str, str], ...]:
    result = agent.verify_against_constraints(
        source_document_id=_RECEIPT_DOC,
        purchase_items=_purchase_items(),
        candidate_constraints=(constraint,),
    )
    return tuple(sorted((str(f.constraint_id), f.expected_category) for f in result.absent_from_findings))


def test_absent_from_beat_is_identical_across_runs_regardless_of_model_output(
    reader: FirestoreGraphReader, writer: FirestoreGraphWriter
) -> None:
    """The load-bearing assertion: the missing-nut-free-item signal is
    produced by deterministic code, so N runs with N different (even
    adversarial / empty / malformed) model payloads all yield the exact
    same `absent_from` finding."""
    constraint = _nut_free_constraint()
    _seed_prior_verifies_edge(writer, constraint)

    fingerprints = {
        _absent_from_fingerprint(_agent(reader, payload), constraint) for payload in _ADVERSARIAL_PAYLOADS
    }

    assert fingerprints == {((str(_NUT_FREE), "bakery"),)}, (
        "the absent_from beat varied with model output — it must come from "
        "VerificationAgent._check_absent_from, not model discretion"
    )


def test_full_discrepancy_is_identical_across_runs_with_a_stable_payload(
    reader: FirestoreGraphReader, writer: FirestoreGraphWriter
) -> None:
    """With the payload stable (what temperature=0 buys on the real call),
    the whole surfaced exception — the contradicts edge, the opened
    Discrepancy, and the absent_from finding — is identical every run.
    Compared on semantic content only; uuid edge ids and wall-clock
    timestamps are expected to differ and are excluded."""
    constraint = _nut_free_constraint()
    _seed_prior_verifies_edge(writer, constraint)
    stable_payload = _ADVERSARIAL_PAYLOADS[0]

    fingerprints: set[tuple[object, ...]] = set()
    for _ in range(_RUNS):
        result = _agent(reader, stable_payload).verify_against_constraints(
            source_document_id=_RECEIPT_DOC,
            purchase_items=_purchase_items(),
            candidate_constraints=(constraint,),
        )
        edge_fp = tuple(
            sorted((e.edge_type.value, str(e.to_id), e.metadata.get("reasoning", "")) for e in result.edges)
        )
        disc_fp = tuple(
            sorted(
                (str(d.constraint_id), d.new_verdict, d.conflicting_prior_edge_type.value)
                for d in result.discrepancies
            )
        )
        absent_fp = tuple(
            sorted((str(f.constraint_id), f.expected_category) for f in result.absent_from_findings)
        )
        fingerprints.add((edge_fp, disc_fp, absent_fp))

    assert len(fingerprints) == 1
    (only,) = fingerprints
    only_edge_fp, only_disc_fp, only_absent_fp = only
    expected_reasoning = "Mixed nuts directly contain the forbidden allergen."
    assert only_edge_fp == ((EdgeType.CONTRADICTS.value, str(_NUT_FREE), expected_reasoning),)
    assert only_disc_fp == ((str(_NUT_FREE), "contradicts", EdgeType.VERIFIES.value),)
    assert only_absent_fp == ((str(_NUT_FREE), "bakery"),)


def test_prior_verifies_edge_is_never_overwritten_across_runs(
    reader: FirestoreGraphReader, writer: FirestoreGraphWriter
) -> None:
    """A3c holds no GraphWriter — no matter how many times the beat runs,
    the prior `verifies` edge the discrepancy conflicts with stays
    readable (spec §15.2 A3c forbidden: silently overwriting)."""
    constraint = _nut_free_constraint()
    _seed_prior_verifies_edge(writer, constraint)

    for _ in range(_RUNS):
        _agent(reader, _ADVERSARIAL_PAYLOADS[0]).verify_against_constraints(
            source_document_id=_RECEIPT_DOC,
            purchase_items=_purchase_items(),
            candidate_constraints=(constraint,),
        )
        assert reader.neighbours(constraint.id, EdgeType.VERIFIES) != ()

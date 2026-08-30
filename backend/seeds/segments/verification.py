"""Segment: the engineered verification receipt (spec §24 3:05 exception
build-up / §26 "The verification pair (build this deliberately)").

One crumpled thermal grocery receipt that, checked against the graph,
does all three of the things the spec calls for, deterministically:

* **(a) discharges** an open shopping `Obligation`
  (`discharges` LEDGER_EVENT -> OBLIGATION);
* **(b) substitutes** against the planned list — a store-brand paneer was
  bought instead of the usual Amul paneer from last week's receipt
  (`substitutes` PURCHASE_ITEM -> PURCHASE_ITEM);
* **(c) is missing** the nut-free bread the hard `constraint-nut-free`
  requires — an `absent_from` signal (CONSTRAINT -> SOURCE_DOCUMENT):
  the receipt arrived, the nut-free item is not on it, so the constraint
  the system believes it is honouring is not actually confirmed in the
  physical world (`GharOS_Build_Spec_v2.md` §5.5, the highest-value case).
"""

from __future__ import annotations

from datetime import timedelta

from contracts.graph_types import (
    Derivation,
    Edge,
    EdgeType,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    PurchaseItem,
    SourceDocument,
)

from ._common import NOW, Segment, edge, prov
from .roster import PERSON_PRIYA, PERSON_ROHAN

DOC_RECEIPT = "doc-verification-receipt"
CONSTRAINT_NUT_FREE = NodeId("constraint-nut-free")  # frozen base id
VENDOR_FRESHMART = NodeId("vendor-freshmart")  # frozen base id
LEDGER_PRIOR_WEEK = NodeId("ledger-freshmart-debit-prior-week")  # frozen base id

OBLIGATION_WEEKEND_SHOP = NodeId("obligation-fd-weekend-shop")
LEDGER_RECEIPT = NodeId("ledger-fd-verification-receipt")
ITEM_STOREBRAND_PANEER = NodeId("item-fd-vr-storebrand-paneer")
ITEM_PLANNED_AMUL_PANEER = NodeId("item-fd-vr-planned-amul-paneer")


def build() -> Segment:
    nodes: list[object] = []
    edges: list[Edge] = []

    receipt_doc = SourceDocument(
        id=NodeId(DOC_RECEIPT),
        provenance=prov(source_document_id=DOC_RECEIPT, region="whole-document", confidence=0.82),
        channel="upload",
        raw_payload_ref="photos/freshmart-thermal-receipt-crumpled-2026-08-26.jpg",
        document_type="receipt",
        ingested_at=NOW - timedelta(hours=20),
        original_language="en",
    )
    nodes.append(receipt_doc)

    shop_obl = Obligation(
        id=OBLIGATION_WEEKEND_SHOP,
        provenance=prov(
            source_document_id=DOC_RECEIPT,
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
        title="Do the weekend grocery shop (list: nut-free bread, atta, paneer, eggs, oats)",
        obligation_type="errand",
        due_at=NOW - timedelta(days=1),
        must_start_by=None,
        effort_estimate_minutes=45,
        status=ObligationStatus.COMPLETED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    nodes.append(shop_obl)

    receipt_debit = LedgerEvent(
        id=LEDGER_RECEIPT,
        provenance=prov(source_document_id=DOC_RECEIPT, region="total-line", confidence=0.9),
        kind=LedgerEventKind.DEBIT,
        amount=1180.0,
        currency="INR",
        occurred_at=NOW - timedelta(days=1),
        counterparty_raw="FRESHMART GROCERY",
    )
    nodes.append(receipt_debit)

    def _item(item_id: str, desc: str, total: float, ledger_id: NodeId, region: str) -> PurchaseItem:
        return PurchaseItem(
            id=NodeId(item_id),
            provenance=prov(source_document_id=DOC_RECEIPT, region=region, confidence=0.85),
            ledger_event_id=ledger_id,
            description=desc,
            normalized_category="groceries",
            quantity=1.0,
            unit_price=total,
            line_total=total,
        )

    atta = _item("item-fd-vr-atta", "Aashirvaad atta 5kg", 320.0, LEDGER_RECEIPT, "line-1")
    eggs = _item("item-fd-vr-eggs", "Farm eggs x12", 96.0, LEDGER_RECEIPT, "line-2")
    oats = _item("item-fd-vr-oats", "Quaker oats 1kg", 210.0, LEDGER_RECEIPT, "line-3")
    storebrand_paneer = _item(
        str(ITEM_STOREBRAND_PANEER), "Freshmart store-brand paneer 400g", 148.0, LEDGER_RECEIPT, "line-4"
    )
    # The planned item — last week's actual Amul paneer, on the frozen
    # base's prior-week receipt debit (same pattern as base's pi4/pi5).
    planned_amul_paneer = PurchaseItem(
        id=ITEM_PLANNED_AMUL_PANEER,
        provenance=prov(
            source_document_id=DOC_RECEIPT,
            region="planned-list-item-3",
            derivation=Derivation.INFERRED,
            confidence=0.7,
        ),
        ledger_event_id=LEDGER_PRIOR_WEEK,
        description="Amul paneer 400g (the usual / planned item)",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=190.0,
        line_total=190.0,
    )
    nodes += [atta, eggs, oats, storebrand_paneer, planned_amul_paneer]

    for pi in (atta, eggs, oats, storebrand_paneer):
        edges.append(
            edge(
                f"e-fd-lineitem-{pi.id}",
                EdgeType.LINE_ITEM_OF,
                pi.id,
                LEDGER_RECEIPT,
                source_document_id=DOC_RECEIPT,
            )
        )
        edges.append(
            edge(
                f"e-fd-effort-{pi.id}-rohan",
                EdgeType.EVIDENCES_EFFORT,
                pi.id,
                PERSON_ROHAN,
                source_document_id=DOC_RECEIPT,
            )
        )
    edges.append(
        edge(
            "e-fd-lineitem-planned-amul",
            EdgeType.LINE_ITEM_OF,
            ITEM_PLANNED_AMUL_PANEER,
            LEDGER_PRIOR_WEEK,
            source_document_id=DOC_RECEIPT,
        )
    )

    edges += [
        edge(
            "e-fd-implies-weekend-shop",
            EdgeType.IMPLIES,
            NodeId(DOC_RECEIPT),
            OBLIGATION_WEEKEND_SHOP,
            source_document_id=DOC_RECEIPT,
        ),
        edge(
            "e-fd-owned-weekend-shop",
            EdgeType.OWNED_BY,
            OBLIGATION_WEEKEND_SHOP,
            PERSON_ROHAN,
            source_document_id=DOC_RECEIPT,
        ),
        edge(
            "e-fd-owed-verification-receipt",
            EdgeType.OWED_TO,
            LEDGER_RECEIPT,
            VENDOR_FRESHMART,
            source_document_id=DOC_RECEIPT,
        ),
        # (a) the receipt settles the shopping obligation
        edge(
            "e-fd-discharges-receipt-shop",
            EdgeType.DISCHARGES,
            LEDGER_RECEIPT,
            OBLIGATION_WEEKEND_SHOP,
            source_document_id=DOC_RECEIPT,
            region="whole-document",
            derivation=Derivation.EXTRACTED,
            confidence=0.9,
        ),
        # (b) store-brand paneer bought instead of the planned Amul
        edge(
            "e-fd-substitutes-paneer",
            EdgeType.SUBSTITUTES,
            ITEM_STOREBRAND_PANEER,
            ITEM_PLANNED_AMUL_PANEER,
            source_document_id=DOC_RECEIPT,
            region="line-4",
            derivation=Derivation.INFERRED,
            confidence=0.86,
        ),
        # (c) nut-free bread expected on this receipt, absent -> silent non-compliance
        edge(
            "e-fd-absent-nutfree-receipt",
            EdgeType.ABSENT_FROM,
            CONSTRAINT_NUT_FREE,
            NodeId(DOC_RECEIPT),
            source_document_id=DOC_RECEIPT,
            region="line-item-block",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
        # Priya is the person the nut-free constraint's compliance is on the
        # hook for, even though Rohan did this shop — effort evidence vs
        # constraint owner diverge, which is the point of the beat.
        edge(
            "e-fd-effort-shop-priya-context",
            EdgeType.EVIDENCES_EFFORT,
            LEDGER_RECEIPT,
            PERSON_PRIYA,
            source_document_id=DOC_RECEIPT,
            confidence=0.5,
        ),
    ]

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

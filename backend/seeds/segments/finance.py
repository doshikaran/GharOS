"""Segment: three months of financial signals and the money 'leak'
(spec §24 1:40 Ledger beat, §26 "Financial signals: 3 months of UPI SMS
including one silent price hike, one unused recurring service, one
duplicate charge").

The three leak forms, all deterministically surfaceable by the Ledger
subsystem's own queries against this data:

* **silent price hike** — `commitment-fd-broadband`'s `price_history`
  climbs 999 -> 1199 -> 1499 over three months with no plan change, and
  three real DEBIT `LedgerEvent`s `belongs_to` it at those amounts;
* **unused recurring service** — `commitment-fd-streaming` is `active`
  with a `last_used_at` ~4 months in the past, still billing 649/month;
* **duplicate charge** — two byte-identical DEBITs to "BIGBASKET", same
  amount, same day.

Also seeds: monthly salary/advance `LedgerEvent`s for both staff (feeding
`app.solvers.salary_calculator`), the water-purifier purchase +
`PurchaseItem` the warranty obligation `covers`, a restaurant bill with
`evidences_effort`, and a truncated/opaque UPI SMS whose merchant string
resolved only to a low-confidence placeholder vendor (spec §5.4.2 — "low
confidence must not on its own drive a cancellation recommendation").
"""

from __future__ import annotations

from datetime import datetime, timedelta

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
    RecurringCommitment,
    SourceDocument,
    Vendor,
)

from ._common import NOW, Segment, edge, months_ago, prov
from .roster import PERSON_MAYA, PERSON_PRIYA, PERSON_ROHAN, PERSON_SALIM

DOC_BROADBAND_BILL = "doc-broadband-bill-aug"
DOC_WARRANTY = "doc-water-purifier-warranty"
DOC_UPI_TRUNCATED = "doc-upi-sms-truncated"
DOC_RESTAURANT = "doc-restaurant-bill"
DOC_BANK_STATEMENT = "doc-hdfc-statement-q3"

COMMITMENT_BROADBAND = NodeId("commitment-fd-broadband")
COMMITMENT_STREAMING = NodeId("commitment-fd-streaming")
COMMITMENT_MAINTENANCE = NodeId("commitment-society-maintenance")  # frozen base id
VENDOR_SUNRISE = NodeId("vendor-sunrise-society")  # frozen base id

LEDGER_BROADBAND_AUG = NodeId("ledger-fd-broadband-aug")
LEDGER_GROCERY_DUP_1 = NodeId("ledger-fd-grocery-dup-1")
LEDGER_GROCERY_DUP_2 = NodeId("ledger-fd-grocery-dup-2")
LEDGER_UPI_UNMATCHED = NodeId("ledger-fd-upi-unmatched")
ITEM_WATER_PURIFIER = NodeId("item-fd-water-purifier")
OBLIGATION_WARRANTY_CLAIM = NodeId("obligation-fd-purifier-warranty-claim")


def _bill_doc(doc_id: str, *, document_type: str, ref: str, language: str, days_ago: float) -> SourceDocument:
    return SourceDocument(
        id=NodeId(doc_id),
        provenance=prov(source_document_id=doc_id, region="whole-document", confidence=0.9),
        channel="upload" if document_type != "upi_sms_alert" else "sms",
        raw_payload_ref=ref,
        document_type=document_type,
        ingested_at=NOW - timedelta(days=days_ago),
        original_language=language,
    )


def _debit(
    event_id: str,
    *,
    amount: float,
    occurred_at: datetime,
    counterparty_raw: str,
    doc_id: str,
    kind: LedgerEventKind = LedgerEventKind.DEBIT,
    confidence: float = 0.9,
    region: str = "transaction-row",
) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(event_id),
        provenance=prov(source_document_id=doc_id, region=region, confidence=confidence),
        kind=kind,
        amount=amount,
        currency="INR",
        occurred_at=occurred_at,
        counterparty_raw=counterparty_raw,
    )


def build() -> Segment:  # noqa: C901 - flat data manifest
    nodes: list[object] = []
    edges: list[Edge] = []

    # -- documents --------------------------------------------------------
    nodes += [
        _bill_doc(
            DOC_BROADBAND_BILL,
            document_type="utility_bill",
            ref="scans/act-fibernet-invoice-aug-2026.pdf",
            language="en",
            days_ago=7,
        ),
        _bill_doc(
            DOC_WARRANTY,
            document_type="warranty",
            ref="scans/aquapure-warranty-card-photo.jpg",
            language="en",
            days_ago=19,
        ),
        _bill_doc(
            DOC_UPI_TRUNCATED,
            document_type="upi_sms_alert",
            ref="sms/upi-alert-2026-08-18-truncated.txt",
            language="en",
            days_ago=12,
        ),
        _bill_doc(
            DOC_RESTAURANT,
            document_type="receipt",
            ref="photos/cafe-madras-bill-crumpled.jpg",
            language="en",
            days_ago=11,
        ),
        _bill_doc(
            DOC_BANK_STATEMENT,
            document_type="bank_statement",
            ref="scans/hdfc-statement-jun-aug-2026.pdf",
            language="en",
            days_ago=4,
        ),
    ]

    # -- vendors --------------------------------------------------------
    def _vendor(
        vid: str, category: str, doc_id: str, *, reliability: float | None, latency: float | None
    ) -> Vendor:
        return Vendor(
            id=NodeId(vid),
            provenance=prov(source_document_id=doc_id, region="merchant-header", confidence=0.82),
            category=category,
            contacts=(),
            reliability_score=reliability,
            response_latency_hours=latency,
        )

    v_act = _vendor(
        "vendor-fd-act-fibernet", "internet_service", DOC_BROADBAND_BILL, reliability=0.8, latency=24.0
    )
    v_stream = _vendor(
        "vendor-fd-cinestream", "streaming", DOC_BANK_STATEMENT, reliability=None, latency=None
    )
    v_bigbasket = _vendor("vendor-fd-bigbasket", "grocery", DOC_BANK_STATEMENT, reliability=0.7, latency=None)
    v_aquapure = _vendor("vendor-fd-aquapure", "appliances", DOC_WARRANTY, reliability=0.75, latency=72.0)
    v_restaurant = _vendor("vendor-fd-cafe-madras", "dining", DOC_RESTAURANT, reliability=None, latency=None)
    v_unresolved = Vendor(
        id=NodeId("vendor-fd-unresolved-upi"),
        provenance=prov(
            source_document_id=DOC_UPI_TRUNCATED,
            region="merchant-string",
            derivation=Derivation.AMBIGUOUS,
            confidence=0.4,
        ),
        category="unresolved",
        contacts=(),
        reliability_score=None,
        response_latency_hours=None,
    )
    nodes += [v_act, v_stream, v_bigbasket, v_aquapure, v_restaurant, v_unresolved]

    # -- recurring commitments ----------------------------------------
    broadband = RecurringCommitment(
        id=COMMITMENT_BROADBAND,
        provenance=prov(source_document_id=DOC_BROADBAND_BILL, region="plan-summary", confidence=0.9),
        label="ACT Fibernet broadband (100 Mbps plan, unchanged)",
        counterparty="ACT Fibernet",
        amount=1499.0,
        cadence="monthly",
        price_history=(
            (months_ago(3), 999.0),
            (months_ago(2), 1199.0),
            (months_ago(1), 1499.0),
        ),
        last_used_at=NOW - timedelta(days=1),
        status="active",
    )
    streaming = RecurringCommitment(
        id=COMMITMENT_STREAMING,
        provenance=prov(
            source_document_id=DOC_BANK_STATEMENT, region="recurring-debits-block", confidence=0.85
        ),
        label="CineStream Premium",
        counterparty="CineStream",
        amount=649.0,
        cadence="monthly",
        price_history=((months_ago(6), 649.0),),
        last_used_at=NOW - timedelta(days=124),
        status="active",
    )
    nodes += [broadband, streaming]

    # -- one payment/review obligation per bill-shaped document, so each
    #    SOURCE_DOCUMENT has a real incident edge (and the demo's implied-
    #    obligation / load picture is richer) --------------------------
    pay_broadband = Obligation(
        id=NodeId("obligation-fd-pay-broadband-aug"),
        provenance=prov(source_document_id=DOC_BROADBAND_BILL, region="amount-due", confidence=0.92),
        title="Pay the August broadband bill (INR 1,499 - up from INR 999 in June)",
        obligation_type="payment",
        due_at=NOW + timedelta(days=4),
        must_start_by=None,
        effort_estimate_minutes=5,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    review_upi = Obligation(
        id=NodeId("obligation-fd-review-unknown-charge"),
        provenance=prov(
            source_document_id=DOC_UPI_TRUNCATED,
            region="body",
            derivation=Derivation.INFERRED,
            confidence=0.55,
        ),
        title="Review an unrecognised INR 3,499 UPI debit (merchant string unresolved, do not auto-cancel)",
        obligation_type="admin",
        due_at=NOW + timedelta(days=2),
        must_start_by=None,
        effort_estimate_minutes=15,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    log_dining = Obligation(
        id=NodeId("obligation-fd-log-dining-spend"),
        provenance=prov(
            source_document_id=DOC_RESTAURANT,
            region="total-line",
            derivation=Derivation.INFERRED,
            confidence=0.6,
        ),
        title="Log Saturday's INR 1,840 dining-out spend against the monthly eating-out budget",
        obligation_type="admin",
        due_at=NOW - timedelta(days=9),
        must_start_by=None,
        effort_estimate_minutes=5,
        status=ObligationStatus.COMPLETED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    nodes += [pay_broadband, review_upi, log_dining]
    edges += [
        edge(
            "e-fd-states-pay-broadband",
            EdgeType.STATES,
            NodeId(DOC_BROADBAND_BILL),
            pay_broadband.id,
            source_document_id=DOC_BROADBAND_BILL,
            region="amount-due",
            derivation=Derivation.EXTRACTED,
        ),
        edge(
            "e-fd-owned-pay-broadband",
            EdgeType.OWNED_BY,
            pay_broadband.id,
            PERSON_PRIYA,
            source_document_id=DOC_BROADBAND_BILL,
        ),
        edge(
            "e-fd-implies-review-upi",
            EdgeType.IMPLIES,
            NodeId(DOC_UPI_TRUNCATED),
            review_upi.id,
            source_document_id=DOC_UPI_TRUNCATED,
        ),
        edge(
            "e-fd-owned-review-upi",
            EdgeType.OWNED_BY,
            review_upi.id,
            PERSON_PRIYA,
            source_document_id=DOC_UPI_TRUNCATED,
        ),
        edge(
            "e-fd-implies-log-dining",
            EdgeType.IMPLIES,
            NodeId(DOC_RESTAURANT),
            log_dining.id,
            source_document_id=DOC_RESTAURANT,
        ),
        edge(
            "e-fd-owned-log-dining",
            EdgeType.OWNED_BY,
            log_dining.id,
            PERSON_ROHAN,
            source_document_id=DOC_RESTAURANT,
        ),
    ]

    # -- broadband debits: the silent hike, three months ------------
    bb = [
        _debit(
            "ledger-fd-broadband-jun",
            amount=999.0,
            occurred_at=months_ago(3),
            counterparty_raw="ACT FIBERNET",
            doc_id=DOC_BANK_STATEMENT,
        ),
        _debit(
            "ledger-fd-broadband-jul",
            amount=1199.0,
            occurred_at=months_ago(2),
            counterparty_raw="ACT FIBERNET",
            doc_id=DOC_BANK_STATEMENT,
        ),
        _debit(
            str(LEDGER_BROADBAND_AUG),
            amount=1499.0,
            occurred_at=months_ago(1),
            counterparty_raw="ACT FIBERNET",
            doc_id=DOC_BROADBAND_BILL,
            region="amount-due",
        ),
    ]
    nodes += bb
    for ev in bb:
        edges += [
            edge(
                f"e-fd-belongs-{ev.id}",
                EdgeType.BELONGS_TO,
                ev.id,
                COMMITMENT_BROADBAND,
                source_document_id=DOC_BANK_STATEMENT,
            ),
            edge(
                f"e-fd-owed-{ev.id}", EdgeType.OWED_TO, ev.id, v_act.id, source_document_id=DOC_BANK_STATEMENT
            ),
        ]

    # -- streaming debits: the unused service, three months ---------
    st = [
        _debit(
            f"ledger-fd-streaming-{tag}",
            amount=649.0,
            occurred_at=when,
            counterparty_raw="CINESTREAM*PREMIUM",
            doc_id=DOC_BANK_STATEMENT,
        )
        for tag, when in (("jun", months_ago(3)), ("jul", months_ago(2)), ("aug", months_ago(1)))
    ]
    nodes += st
    for ev in st:
        edges += [
            edge(
                f"e-fd-belongs-{ev.id}",
                EdgeType.BELONGS_TO,
                ev.id,
                COMMITMENT_STREAMING,
                source_document_id=DOC_BANK_STATEMENT,
            ),
            edge(
                f"e-fd-owed-{ev.id}",
                EdgeType.OWED_TO,
                ev.id,
                v_stream.id,
                source_document_id=DOC_BANK_STATEMENT,
            ),
        ]

    # -- society maintenance history (frozen base has only the Aug debit)
    mnt = [
        _debit(
            "ledger-fd-maintenance-jun",
            amount=2300.0,
            occurred_at=months_ago(3),
            counterparty_raw="SUNRISE SOCIETY MAINT",
            doc_id=DOC_BANK_STATEMENT,
        ),
        _debit(
            "ledger-fd-maintenance-jul",
            amount=2500.0,
            occurred_at=months_ago(2),
            counterparty_raw="SUNRISE SOCIETY MAINT",
            doc_id=DOC_BANK_STATEMENT,
        ),
    ]
    nodes += mnt
    for ev in mnt:
        edges += [
            edge(
                f"e-fd-belongs-{ev.id}",
                EdgeType.BELONGS_TO,
                ev.id,
                COMMITMENT_MAINTENANCE,
                source_document_id=DOC_BANK_STATEMENT,
            ),
            edge(
                f"e-fd-owed-{ev.id}",
                EdgeType.OWED_TO,
                ev.id,
                VENDOR_SUNRISE,
                source_document_id=DOC_BANK_STATEMENT,
            ),
        ]

    # -- the duplicate charge --------------------------------------
    dup_day = NOW - timedelta(days=8)
    dup1 = _debit(
        str(LEDGER_GROCERY_DUP_1),
        amount=1250.0,
        occurred_at=dup_day,
        counterparty_raw="BIGBASKET",
        doc_id=DOC_BANK_STATEMENT,
    )
    dup2 = _debit(
        str(LEDGER_GROCERY_DUP_2),
        amount=1250.0,
        occurred_at=dup_day,
        counterparty_raw="BIGBASKET",
        doc_id=DOC_BANK_STATEMENT,
    )
    nodes += [dup1, dup2]
    for ev in (dup1, dup2):
        edges.append(
            edge(
                f"e-fd-owed-{ev.id}",
                EdgeType.OWED_TO,
                ev.id,
                v_bigbasket.id,
                source_document_id=DOC_BANK_STATEMENT,
            )
        )
    pi_dup = PurchaseItem(
        id=NodeId("item-fd-bigbasket-order"),
        provenance=prov(source_document_id=DOC_BANK_STATEMENT, region="bigbasket-line", confidence=0.7),
        ledger_event_id=dup1.id,
        description="BigBasket weekly grocery order",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=1250.0,
        line_total=1250.0,
    )
    nodes.append(pi_dup)
    edges.append(
        edge(
            "e-fd-lineitem-bigbasket",
            EdgeType.LINE_ITEM_OF,
            pi_dup.id,
            dup1.id,
            source_document_id=DOC_BANK_STATEMENT,
        )
    )

    # -- staff salary + advance cycles ---------------------------
    salary_events = [
        (
            _debit(
                "ledger-fd-maya-salary-jun",
                amount=8000.0,
                occurred_at=months_ago(3),
                counterparty_raw="MAYA BAI",
                doc_id=DOC_BANK_STATEMENT,
                kind=LedgerEventKind.SALARY,
            ),
            PERSON_MAYA,
        ),
        (
            _debit(
                "ledger-fd-maya-salary-jul",
                amount=8000.0,
                occurred_at=months_ago(2),
                counterparty_raw="MAYA BAI",
                doc_id=DOC_BANK_STATEMENT,
                kind=LedgerEventKind.SALARY,
            ),
            PERSON_MAYA,
        ),
        (
            _debit(
                "ledger-fd-salim-salary-jun",
                amount=12000.0,
                occurred_at=months_ago(3),
                counterparty_raw="SALIM",
                doc_id=DOC_BANK_STATEMENT,
                kind=LedgerEventKind.SALARY,
            ),
            PERSON_SALIM,
        ),
        (
            _debit(
                "ledger-fd-salim-salary-jul",
                amount=12000.0,
                occurred_at=months_ago(2),
                counterparty_raw="SALIM",
                doc_id=DOC_BANK_STATEMENT,
                kind=LedgerEventKind.SALARY,
            ),
            PERSON_SALIM,
        ),
        (
            _debit(
                "ledger-fd-salim-advance",
                amount=3000.0,
                occurred_at=NOW - timedelta(days=16),
                counterparty_raw="SALIM",
                doc_id="doc-salim-register-aug",
                kind=LedgerEventKind.ADVANCE,
                confidence=0.8,
                region="margin-note",
            ),
            PERSON_SALIM,
        ),
    ]
    for ev, person in salary_events:
        nodes.append(ev)
        edges.append(
            edge(f"e-fd-owed-{ev.id}", EdgeType.OWED_TO, ev.id, person, source_document_id=DOC_BANK_STATEMENT)
        )

    # -- weekly grocery debits (extra history for spend_by_category) --
    grocery = [
        _debit(
            "ledger-fd-grocery-16d",
            amount=780.0,
            occurred_at=NOW - timedelta(days=16),
            counterparty_raw="FRESHMART GROCERY",
            doc_id=DOC_BANK_STATEMENT,
        ),
        _debit(
            "ledger-fd-grocery-23d",
            amount=920.0,
            occurred_at=NOW - timedelta(days=23),
            counterparty_raw="FRESHMART GROCERY",
            doc_id=DOC_BANK_STATEMENT,
        ),
    ]
    for ev in grocery:
        nodes.append(ev)
        edges.append(
            edge(
                f"e-fd-owed-{ev.id}",
                EdgeType.OWED_TO,
                ev.id,
                NodeId("vendor-freshmart"),
                source_document_id=DOC_BANK_STATEMENT,
            )
        )
        pi = PurchaseItem(
            id=NodeId(f"item-{ev.id}"),
            provenance=prov(source_document_id=DOC_BANK_STATEMENT, region="freshmart-line", confidence=0.7),
            ledger_event_id=ev.id,
            description="Weekly groceries (Freshmart)",
            normalized_category="groceries",
            quantity=1.0,
            unit_price=ev.amount,
            line_total=ev.amount,
        )
        nodes.append(pi)
        edges += [
            edge(
                f"e-fd-lineitem-{pi.id}",
                EdgeType.LINE_ITEM_OF,
                pi.id,
                ev.id,
                source_document_id=DOC_BANK_STATEMENT,
            ),
            edge(
                f"e-fd-effort-{pi.id}-priya",
                EdgeType.EVIDENCES_EFFORT,
                pi.id,
                PERSON_PRIYA,
                source_document_id=DOC_BANK_STATEMENT,
            ),
        ]

    # -- water-purifier purchase + warranty (claim-or-lose) `covers` --
    purifier_debit = _debit(
        "ledger-fd-purifier-purchase",
        amount=9500.0,
        occurred_at=NOW - timedelta(days=20),
        counterparty_raw="AQUAPURE SYSTEMS",
        doc_id=DOC_WARRANTY,
        region="purchase-line",
    )
    purifier_item = PurchaseItem(
        id=ITEM_WATER_PURIFIER,
        provenance=prov(source_document_id=DOC_WARRANTY, region="model-and-price", confidence=0.85),
        ledger_event_id=purifier_debit.id,
        description="AquaPure RO+UV water purifier (installed)",
        normalized_category="appliances",
        quantity=1.0,
        unit_price=9500.0,
        line_total=9500.0,
    )
    warranty_claim = Obligation(
        id=OBLIGATION_WARRANTY_CLAIM,
        provenance=prov(
            source_document_id=DOC_WARRANTY,
            region="registration-clause",
            derivation=Derivation.INFERRED,
            confidence=0.86,
        ),
        title="Register the AquaPure water-purifier warranty before 20 Sep (claim-or-lose)",
        obligation_type="admin",
        due_at=datetime(2026, 9, 20, 17, tzinfo=NOW.tzinfo),
        must_start_by=None,
        effort_estimate_minutes=15,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    nodes += [purifier_debit, purifier_item, warranty_claim]
    edges += [
        edge(
            "e-fd-owed-purifier",
            EdgeType.OWED_TO,
            purifier_debit.id,
            v_aquapure.id,
            source_document_id=DOC_WARRANTY,
        ),
        edge(
            "e-fd-lineitem-purifier",
            EdgeType.LINE_ITEM_OF,
            purifier_item.id,
            purifier_debit.id,
            source_document_id=DOC_WARRANTY,
        ),
        edge(
            "e-fd-states-warranty-claim",
            EdgeType.STATES,
            NodeId(DOC_WARRANTY),
            warranty_claim.id,
            source_document_id=DOC_WARRANTY,
            region="registration-clause",
            derivation=Derivation.EXTRACTED,
        ),
        edge(
            "e-fd-covers-warranty-purifier",
            EdgeType.COVERS,
            warranty_claim.id,
            purifier_item.id,
            source_document_id=DOC_WARRANTY,
            region="model-and-price",
        ),
        edge(
            "e-fd-owned-warranty-claim",
            EdgeType.OWNED_BY,
            warranty_claim.id,
            PERSON_PRIYA,
            source_document_id=DOC_WARRANTY,
        ),
    ]

    # -- restaurant bill: dining spend + evidences_effort ----------
    restaurant_debit = _debit(
        "ledger-fd-restaurant",
        amount=1840.0,
        occurred_at=NOW - timedelta(days=11),
        counterparty_raw="CAFE MADRAS",
        doc_id=DOC_RESTAURANT,
        region="total-line",
        confidence=0.9,
    )
    nodes.append(restaurant_debit)
    edges.append(
        edge(
            "e-fd-owed-restaurant",
            EdgeType.OWED_TO,
            restaurant_debit.id,
            v_restaurant.id,
            source_document_id=DOC_RESTAURANT,
        )
    )
    for i, (desc, total) in enumerate(
        (("Family dinner - mains & thali", 1480.0), ("Filter coffee x4 & dessert", 360.0)), start=1
    ):
        pi = PurchaseItem(
            id=NodeId(f"item-fd-restaurant-{i}"),
            provenance=prov(source_document_id=DOC_RESTAURANT, region=f"line-{i}", confidence=0.85),
            ledger_event_id=restaurant_debit.id,
            description=desc,
            normalized_category="dining_out",
            quantity=1.0,
            unit_price=total,
            line_total=total,
        )
        nodes.append(pi)
        edges += [
            edge(
                f"e-fd-lineitem-restaurant-{i}",
                EdgeType.LINE_ITEM_OF,
                pi.id,
                restaurant_debit.id,
                source_document_id=DOC_RESTAURANT,
            ),
            edge(
                f"e-fd-effort-restaurant-{i}-rohan",
                EdgeType.EVIDENCES_EFFORT,
                pi.id,
                PERSON_ROHAN,
                source_document_id=DOC_RESTAURANT,
            ),
        ]

    # -- truncated / opaque UPI SMS (unmatched, low confidence) ----
    upi = LedgerEvent(
        id=LEDGER_UPI_UNMATCHED,
        provenance=prov(
            source_document_id=DOC_UPI_TRUNCATED,
            region="body",
            derivation=Derivation.AMBIGUOUS,
            confidence=0.42,
        ),
        kind=LedgerEventKind.DEBIT,
        amount=3499.0,
        currency="INR",
        occurred_at=NOW - timedelta(days=12),
        counterparty_raw="ACH DR*RATN*U/UPI/PAYT...",
    )
    nodes.append(upi)
    edges.append(
        edge(
            "e-fd-owed-upi-unmatched",
            EdgeType.OWED_TO,
            upi.id,
            v_unresolved.id,
            source_document_id=DOC_UPI_TRUNCATED,
            derivation=Derivation.AMBIGUOUS,
            confidence=0.42,
        )
    )

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

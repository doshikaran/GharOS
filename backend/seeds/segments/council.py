"""Segment: the Household Council 'car decision' (spec §24 2:40-3:05).

A resolved `Decision` with four `Branch`es, `CouncilPosition`s from
genuinely different subgraphs, a `conceded_by` edge, and a deterministic
resolution — the whole deliberation as a walkable graph record:

* **A42 Finance** reasons from the real Ledger (the society hike, the
  broadband creep, the unused streaming charge) -> thin EMI headroom;
* **A45 Logistics** reasons from the real recurring trips -> a 5-door;
* **A43 Care** contributes a **hard constraint that eliminates an
  option** (`constraint-fd-dadi-mobility`: a 3-door with a high sill
  cannot take a wheeled walker + assisted transfer) rather than scoring;
* **A47 Member Delegates** for Priya and Rohan score in genuine conflict
  from behaviourally-derived valuation profiles;
* **A48 Adversary** attacks the leading option with the household's own
  history (major purchases here have run ~19% over predicted).

Resolution: keep the current car + ring-fenced cab budget; Rohan concedes
the new car (`conceded_by`).
"""

from __future__ import annotations

from datetime import timedelta

from contracts.graph_types import (
    AgentId,
    Branch,
    CouncilPosition,
    Decision,
    DecisionStatus,
    Derivation,
    Edge,
    EdgeType,
    NodeId,
    SourceDocument,
)

from ._common import NOW, Segment, edge, prov
from .roster import PERSON_ROHAN

DOC_QUOTE_NEWCAR = "doc-car-quote-newcar"
DOC_LISTING_USEDCAR = "doc-car-listing-usedcar"
DOC_BANK_STATEMENT = "doc-hdfc-statement-q3"  # seeded by the finance segment

DECISION_CAR = NodeId("decision-fd-car-purchase")
BRANCH_NEW_HATCHBACK = NodeId("branch-fd-new-hatchback")
BRANCH_USED_SEDAN = NodeId("branch-fd-used-sedan")
BRANCH_USED_3DOOR = NodeId("branch-fd-used-3door")
BRANCH_KEEP_AND_CABS = NodeId("branch-fd-keep-and-cabs")

CONSTRAINT_DADI_MOBILITY = NodeId("constraint-fd-dadi-mobility")


def build() -> Segment:
    nodes: list[object] = []
    edges: list[Edge] = []

    quote_doc = SourceDocument(
        id=NodeId(DOC_QUOTE_NEWCAR),
        provenance=prov(source_document_id=DOC_QUOTE_NEWCAR, region="whole-document", confidence=0.9),
        channel="upload",
        raw_payload_ref="scans/maruti-arena-quote-2026-08.pdf",
        document_type="quote_estimate",
        ingested_at=NOW - timedelta(days=6),
        original_language="en",
    )
    listing_doc = SourceDocument(
        id=NodeId(DOC_LISTING_USEDCAR),
        provenance=prov(source_document_id=DOC_LISTING_USEDCAR, region="whole-document", confidence=0.85),
        channel="upload",
        raw_payload_ref="screenshots/olx-used-car-listings-2026-08.png",
        document_type="quote_estimate",
        ingested_at=NOW - timedelta(days=5),
        original_language="en",
    )
    nodes += [quote_doc, listing_doc]

    decision = Decision(
        id=DECISION_CAR,
        provenance=prov(
            source_document_id=DOC_QUOTE_NEWCAR,
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
        question="Buy a family car now, and if so which?",
        trigger=(
            "Rohan raised needing a second vehicle after the Bengaluru trip; Dadi's mobility "
            "needs and the school runs strain the current single-car arrangement."
        ),
        status=DecisionStatus.RESOLVED,
        resolution_summary=(
            "Keep the current car and ring-fence a monthly cab budget for the next two quarters; "
            "revisit after Aarav's board exams."
        ),
        rationale=(
            "Finance: the society maintenance and broadband have both crept up and a streaming "
            "mandate is unused - EMI headroom is thin. Care: a hard mobility constraint eliminates "
            "the cheapest (3-door) option outright. Adversary: this household's major purchases have "
            "run ~19% over the quoted figure. The cab budget carries the real recurring trips at "
            "lower committed cost and no debt."
        ),
    )
    nodes.append(decision)

    branches = [
        Branch(
            id=BRANCH_NEW_HATCHBACK,
            provenance=prov(source_document_id=DOC_QUOTE_NEWCAR, region="on-road-price", confidence=0.88),
            decision_id=DECISION_CAR,
            label="Buy a new 5-door hatchback (Maruti, ~INR 7.2L on-road)",
            projected_impacts={
                "upfront": "INR 1.5L down",
                "emi": "INR 11,800 x 60 months",
                "delivery": "4-6 weeks",
                "mobility_fit": "step-free rear entry, fits the walker",
            },
            grounding_refs=(DOC_QUOTE_NEWCAR,),
            critiques=("Adds a 5-year EMI on top of already-rising recurring costs.",),
        ),
        Branch(
            id=BRANCH_USED_SEDAN,
            provenance=prov(source_document_id=DOC_LISTING_USEDCAR, region="listing-2", confidence=0.8),
            decision_id=DECISION_CAR,
            label="Buy a 3-year-old used sedan (~INR 5.5L)",
            projected_impacts={
                "upfront": "INR 5.5L cash",
                "emi": "none",
                "warranty_risk": "out of manufacturer warranty",
                "mobility_fit": "acceptable, low sill",
            },
            grounding_refs=(DOC_LISTING_USEDCAR,),
            critiques=("Drains the emergency cash buffer; no warranty cover.",),
        ),
        Branch(
            id=BRANCH_USED_3DOOR,
            provenance=prov(source_document_id=DOC_LISTING_USEDCAR, region="listing-5", confidence=0.78),
            decision_id=DECISION_CAR,
            label="Buy a used 3-door hatchback (~INR 3.8L, cheapest)",
            projected_impacts={
                "upfront": "INR 3.8L cash",
                "emi": "none",
                "mobility_fit": "FAILS - high sill, no walker access",
            },
            grounding_refs=(DOC_LISTING_USEDCAR,),
            critiques=("Eliminated by the Care specialist's hard mobility constraint.",),
        ),
        Branch(
            id=BRANCH_KEEP_AND_CABS,
            provenance=prov(
                source_document_id=DOC_BANK_STATEMENT,
                region="recurring-outflow-summary",
                derivation=Derivation.INFERRED,
                confidence=0.82,
            ),
            decision_id=DECISION_CAR,
            label="Keep the current car; ring-fence a monthly cab budget",
            projected_impacts={
                "upfront": "none",
                "committed_cost": "INR 6,000/month cab budget (cancellable)",
                "flexibility": "high - no debt, revisit post-board-exams",
            },
            grounding_refs=(DOC_BANK_STATEMENT,),
            critiques=("Does not solve the two-cars-needed-at-once mornings; relies on cab availability.",),
        ),
    ]
    nodes += branches

    positions = [
        CouncilPosition(
            id=NodeId("position-fd-finance"),
            provenance=prov(
                source_document_id=DOC_BANK_STATEMENT,
                region="recurring-debits-block",
                derivation=Derivation.INFERRED,
                confidence=0.85,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A42"),
            stance="supports",
            branch_id=BRANCH_KEEP_AND_CABS,
            reasoning=(
                "Finance specialist (Ledger subgraph): society maintenance 2,300 -> 2,650, broadband "
                "999 -> 1,499, and an unused 649/month CineStream mandate. Real recurring outflow is "
                "up ~1,850/month already; a 11,800 EMI is not affordable without cutting elsewhere."
            ),
            evidence_refs=(
                "ledger-fd-broadband-jun",
                "ledger-fd-broadband-aug",
                "commitment-fd-streaming",
                "obligation-fd-maintenance-sept",
            ),
        ),
        CouncilPosition(
            id=NodeId("position-fd-logistics"),
            provenance=prov(
                source_document_id=DOC_QUOTE_NEWCAR,
                region="whole-document",
                derivation=Derivation.INFERRED,
                confidence=0.8,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A45"),
            stance="supports",
            branch_id=BRANCH_NEW_HATCHBACK,
            reasoning=(
                "Logistics specialist (Obligation subgraph): recurring school runs for two children, "
                "Dadi's physio and pharmacy trips, and the 7:15 AM field-trip drop all cluster in the "
                "morning. A second 5-door with step-free entry removes the daily clash."
            ),
            evidence_refs=(
                "obligation-fd-pickup-ananya",
                "obligation-fd-fieldtrip-dropoff",
                "obligation-renew-prescription",
            ),
        ),
        CouncilPosition(
            id=NodeId("position-fd-care"),
            provenance=prov(
                source_document_id="doc-dadi-physio-discharge-summary",
                region="equipment-note",
                confidence=0.9,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A43"),
            stance="opposes",
            branch_id=BRANCH_USED_3DOOR,
            reasoning=(
                "Care specialist (Constraint subgraph): constraint-fd-dadi-mobility is HARD - a "
                "wheeled walker plus assisted transfer needs step-free rear access. The 3-door option "
                "is eliminated, not scored down."
            ),
            evidence_refs=("constraint-fd-dadi-mobility", "doc-dadi-physio-discharge-summary"),
        ),
        CouncilPosition(
            id=NodeId("position-fd-delegate-priya"),
            provenance=prov(
                source_document_id=DOC_BANK_STATEMENT,
                region="whole-document",
                derivation=Derivation.INFERRED,
                confidence=0.75,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A47"),
            stance="supports",
            branch_id=BRANCH_KEEP_AND_CABS,
            reasoning=(
                "Member delegate for Priya (valuation-priya): she carries most driving/errand load "
                "already and prices added recurring commitment and monthly-EMI stress high. Prefers "
                "the reversible cab budget."
            ),
            evidence_refs=("valuation-priya", "obligation-pickup-aarav", "obligation-weekly-groceries"),
        ),
        CouncilPosition(
            id=NodeId("position-fd-delegate-rohan"),
            provenance=prov(
                source_document_id=DOC_QUOTE_NEWCAR,
                region="whole-document",
                derivation=Derivation.INFERRED,
                confidence=0.72,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A47"),
            stance="supports",
            branch_id=BRANCH_NEW_HATCHBACK,
            reasoning=(
                "Member delegate for Rohan: he would be the primary driver of the second car and "
                "prices morning flexibility and not depending on cab availability high - a genuine "
                "conflict with Priya's delegate."
            ),
            evidence_refs=("obligation-fd-fieldtrip-dropoff", "obligation-fd-cover-priya-runs"),
        ),
        CouncilPosition(
            id=NodeId("position-fd-adversary"),
            provenance=prov(
                source_document_id=DOC_QUOTE_NEWCAR,
                region="on-road-price",
                derivation=Derivation.INFERRED,
                confidence=0.7,
            ),
            decision_id=DECISION_CAR,
            held_by_agent=AgentId("A48"),
            stance="opposes",
            branch_id=BRANCH_NEW_HATCHBACK,
            reasoning=(
                "Adversary (household history): the water purifier was quoted ~8,000 and cost 9,500 "
                "(+19%); across the last three big buys the overrun averaged ~15%, and the broadband "
                "'unchanged plan' still rose 50%. A 7.2L on-road quote will not hold, and the EMI is "
                "sized off it."
            ),
            evidence_refs=("outcome-water-purifier", "item-fd-water-purifier", "commitment-fd-broadband"),
        ),
    ]
    nodes += positions

    for branch in branches:
        edges.append(
            edge(
                f"e-fd-contains-{branch.id}",
                EdgeType.CONTAINS,
                DECISION_CAR,
                branch.id,
                source_document_id=DOC_QUOTE_NEWCAR,
            )
        )
        for i, ref in enumerate(branch.grounding_refs):
            edges.append(
                edge(
                    f"e-fd-grounded-{branch.id}-{i}",
                    EdgeType.GROUNDED_IN,
                    branch.id,
                    NodeId(ref),
                    source_document_id=str(ref),
                )
            )

    stance_edge_type = {"supports": EdgeType.SUPPORTS, "opposes": EdgeType.OPPOSES}
    for pos in positions:
        assert pos.branch_id is not None
        edges.append(
            edge(
                f"e-fd-{pos.stance}-{pos.id}",
                stance_edge_type[pos.stance],
                pos.id,
                pos.branch_id,
                source_document_id=DOC_QUOTE_NEWCAR,
            )
        )
    edges += [
        edge(
            "e-fd-grounded-care-physio",
            EdgeType.GROUNDED_IN,
            NodeId("position-fd-care"),
            NodeId("doc-dadi-physio-discharge-summary"),
            source_document_id="doc-dadi-physio-discharge-summary",
        ),
        edge(
            "e-fd-grounded-adversary-quote",
            EdgeType.GROUNDED_IN,
            NodeId("position-fd-adversary"),
            NodeId(DOC_QUOTE_NEWCAR),
            source_document_id=DOC_QUOTE_NEWCAR,
        ),
        edge(
            "e-fd-resolved-car",
            EdgeType.RESOLVED_AS,
            DECISION_CAR,
            BRANCH_KEEP_AND_CABS,
            source_document_id=DOC_QUOTE_NEWCAR,
            region="resolution",
            derivation=Derivation.INFERRED,
        ),
        edge(
            "e-fd-conceded-car-rohan",
            EdgeType.CONCEDED_BY,
            DECISION_CAR,
            PERSON_ROHAN,
            source_document_id=DOC_QUOTE_NEWCAR,
            region="resolution",
            derivation=Derivation.INFERRED,
        ),
    ]

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

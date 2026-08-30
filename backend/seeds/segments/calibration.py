"""Segment: enough OUTCOME history for the Simulator's calibration panel
to produce non-generic output (spec §24 3:25 / §26 "Outcome history:
enough completed obligations with predicted-vs-actual variance for
Calibration to produce non-generic output - required").

`app.solvers.calibration_stats.MIN_SAMPLE_SIZE_FOR_CALIBRATION = 3`. The
frozen base seeds exactly one settled OUTCOME each for `school_transition`,
`staff_transition` and `major_purchase` (deliberately thin, N=1). This
segment adds two more settled outcomes to each so `outcome_variance(tag)`
clears the threshold for the three decision categories the demo shows, and
leaves **`relocation` with zero** - this household has never relocated, and
`compute_calibration("relocation", ...)` should honestly report thin
history rather than a fabricated figure.

Every added OBLIGATION is COMPLETED (a closed status - never inflates
`load()`), is `owned_by` a real person, and `completes_into` its OUTCOME
(so `outcome_variance` can walk from the OUTCOME back through the graph).
"""

from __future__ import annotations

from datetime import timedelta

from contracts.graph_types import (
    Derivation,
    Edge,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
)

from ._common import NOW, Segment, edge, prov
from .roster import PERSON_PRIYA, PERSON_ROHAN

# (obligation_id, title, obligation_type, completed_days_ago, owner, source_doc,
#  predicted, actual, variance, tag)
_HISTORY: tuple[tuple[str, str, str, int, NodeId, str, str, str, float, str], ...] = (
    (
        "obligation-fd-cal-ac-purchase",
        "Buy a split AC for the main bedroom",
        "household_purchase",
        75,
        PERSON_ROHAN,
        "doc-hdfc-statement-q3",
        "About INR 32,000 including installation",
        "INR 34,500 including installation and stabiliser",
        2500.0,
        "major_purchase",
    ),
    (
        "obligation-fd-cal-fridge-purchase",
        "Replace the kitchen refrigerator",
        "household_purchase",
        150,
        PERSON_PRIYA,
        "doc-hdfc-statement-q3",
        "About INR 40,000 for a 350L model",
        "INR 47,000 after the model we chose",
        7000.0,
        "major_purchase",
    ),
    (
        "obligation-fd-cal-ananya-admission",
        "Enrol Ananya at Greenfield School (Class 3)",
        "school_administrative",
        120,
        PERSON_PRIYA,
        "doc-greenfield-board-exam-circular",
        "Admission confirmed within a week",
        "Confirmed after 10 days",
        3.0,
        "school_transition",
    ),
    (
        "obligation-fd-cal-aarav-stream-change",
        "Move Aarav onto the science elective track",
        "school_administrative",
        200,
        PERSON_PRIYA,
        "doc-greenfield-board-exam-circular",
        "Smooth switch at the term boundary",
        "Two-week gap in coursework during the switch",
        14.0,
        "school_transition",
    ),
    (
        "obligation-fd-cal-salim-onboarding",
        "Onboard Salim as the household driver",
        "household_staffing",
        90,
        PERSON_PRIYA,
        "doc-salim-register-aug",
        "One-week supervised trial expected",
        "Settled and driving unsupervised within 3 days",
        -4.0,
        "staff_transition",
    ),
    (
        "obligation-fd-cal-cook-departure",
        "Handle the previous cook's departure and handover",
        "household_staffing",
        240,
        PERSON_PRIYA,
        "doc-salim-register-aug",
        "Clean two-week notice period",
        "Left within 4 days; a 10-day cover gap",
        10.0,
        "staff_transition",
    ),
)


def build() -> Segment:
    nodes: list[object] = []
    edges: list[Edge] = []

    for obl_id, title, obl_type, days_ago, owner, doc, predicted, actual, variance, tag in _HISTORY:
        outcome_id = obl_id.replace("obligation-fd-cal-", "outcome-fd-cal-")
        obligation = Obligation(
            id=NodeId(obl_id),
            provenance=prov(
                source_document_id=doc, region="history-log", derivation=Derivation.INFERRED, confidence=0.7
            ),
            title=title,
            obligation_type=obl_type,
            due_at=NOW - timedelta(days=days_ago),
            must_start_by=None,
            effort_estimate_minutes=60,
            status=ObligationStatus.COMPLETED,
            stated_or_implied=ObligationDerivation.STATED,
        )
        outcome = Outcome(
            id=NodeId(outcome_id),
            provenance=prov(
                source_document_id=doc, region="history-log", derivation=Derivation.INFERRED, confidence=0.72
            ),
            predicted=predicted,
            actual=actual,
            variance=variance,
            attribution_tags=(tag,),
        )
        nodes += [obligation, outcome]
        edges += [
            edge(f"e-fd-owned-{obl_id}", EdgeType.OWNED_BY, NodeId(obl_id), owner, source_document_id=doc),
            edge(
                f"e-fd-completes-{obl_id}",
                EdgeType.COMPLETES_INTO,
                NodeId(obl_id),
                NodeId(outcome_id),
                source_document_id=doc,
            ),
        ]

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

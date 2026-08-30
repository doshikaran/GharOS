"""Segment: the rest of the spec §26 roster and its hard constraints.

`seeds.demo_household` already seeds Priya (adult), Aarav (child), Dadi
(elder) and Maya (staff). Spec §26 wants **two adults, two children, one
elder, two staff**, plus "one hard dietary [base: nut-free], one hard
medical schedule, one mobility, one custody or travel" constraint. This
segment adds the missing people and the three missing hard constraints,
plus the board-exam-year `EDUCATION` constraint the demo's Council beat
and spec §26 ("one in a board-exam year") both call for.

Language note: Rohan's profile is Marathi-primary so the §24 voice beat's
"second speaker in Marathi, correctly attributed" has a real voiceprint-
bearing PERSON to attribute to, without mutating the frozen base Dadi.
"""

from __future__ import annotations

from datetime import datetime

from contracts.graph_types import (
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Edge,
    EdgeType,
    NodeId,
    Person,
    PersonRole,
)

from ._common import NOW, Segment, edge, language_profile, prov

# Stable ids other segments (documents, council, verification) reference.
PERSON_ROHAN = NodeId("person-rohan")
PERSON_ANANYA = NodeId("person-ananya")
PERSON_SALIM = NodeId("person-salim")
PERSON_PRIYA = NodeId("person-priya")
PERSON_AARAV = NodeId("person-aarav")
PERSON_DADI = NodeId("person-dadi")
PERSON_MAYA = NodeId("person-maya")

CONSTRAINT_DADI_MOBILITY = NodeId("constraint-fd-dadi-mobility")
CONSTRAINT_DADI_BP_MEDS = NodeId("constraint-fd-dadi-bp-meds")
CONSTRAINT_AARAV_BOARDEXAM = NodeId("constraint-fd-aarav-boardexam")
CONSTRAINT_PRIYA_TRAVEL = NodeId("constraint-fd-priya-travel")

# Every constraint/person here is anchored to a real SOURCE_DOCUMENT that
# `seeds.segments.documents` seeds — no synthetic "onboarding note".
_DOC_FIELDTRIP = "doc-fieldtrip-email"
_DOC_REGISTER = "doc-salim-register-aug"
_DOC_MOBILITY = "doc-dadi-physio-discharge-summary"
_DOC_MEDS = "doc-dadi-cardiology-letter"
_DOC_BOARDEXAM = "doc-greenfield-board-exam-circular"
_DOC_TRAVEL = "doc-priya-travel-itinerary-email"


def build() -> Segment:
    nodes: list[object] = []
    edges: list[Edge] = []

    rohan = Person(
        id=PERSON_ROHAN,
        provenance=prov(source_document_id=_DOC_FIELDTRIP, region="to-line", confidence=0.9),
        display_name="Rohan",
        aliases=("Rohan Sharma", "Papa", "रोहन"),
        role=PersonRole.ADULT,
        can_drive=True,
        can_sign=True,
        has_bank_access=True,
        has_medical_proxy=True,
        contact_channels=("whatsapp:+91-90000-00005", "voice:+91-90000-00005"),
        language_profile=language_profile("mr"),
        voiceprint_ref="voiceprints/rohan.embedding",
        pronunciation_hints="ROH-un",
    )
    ananya = Person(
        id=PERSON_ANANYA,
        provenance=prov(source_document_id=_DOC_FIELDTRIP, region="body-para-1", confidence=0.9),
        display_name="Ananya",
        aliases=("Ananya Sharma", "Anu", "अनन्या"),
        role=PersonRole.CHILD,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=language_profile("en"),
    )
    salim = Person(
        id=PERSON_SALIM,
        provenance=prov(source_document_id=_DOC_REGISTER, region="name-header", confidence=0.85),
        display_name="Salim",
        aliases=("Salim Bhai", "Salim (driver)"),
        role=PersonRole.STAFF,
        can_drive=True,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=("voice:+91-90000-00006",),
        language_profile=language_profile("hi"),
    )
    nodes += [rohan, ananya, salim]

    dadi_mobility = Constraint(
        id=CONSTRAINT_DADI_MOBILITY,
        provenance=prov(source_document_id=_DOC_MOBILITY, region="assessment-para-3", confidence=0.95),
        kind=ConstraintKind.MOBILITY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={
            "aid": "wheeled_walker",
            "stairs": "none",
            "access": "step_free_only",
            "transfer_notice_minutes": "10",
        },
        original_text=(
            "Patient ambulates with a wheeled walker. Step-free access only; no stairs. "
            "Allow ~10 minutes to prepare for any outing."
        ),
    )
    dadi_bp_meds = Constraint(
        id=CONSTRAINT_DADI_BP_MEDS,
        provenance=prov(source_document_id=_DOC_MEDS, region="rx-block", confidence=0.94),
        kind=ConstraintKind.MEDICAL,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={
            "medication": "amlodipine 5mg",
            "schedule": "twice_daily",
            "times": "08:00,20:00",
            "with_food": "yes",
        },
        original_text=(
            "Amlodipine 5mg twice daily, 8 AM and 8 PM, with food. Do not skip. BP diary to be maintained."
        ),
    )
    aarav_boardexam = Constraint(
        id=CONSTRAINT_AARAV_BOARDEXAM,
        provenance=prov(source_document_id=_DOC_BOARDEXAM, region="para-1", confidence=0.93),
        kind=ConstraintKind.EDUCATION,
        severity=ConstraintSeverity.HARD,
        validity_start=datetime(2026, 6, 1, tzinfo=NOW.tzinfo),
        validity_end=datetime(2027, 3, 31, tzinfo=NOW.tzinfo),
        structured={
            "grade": "10",
            "exam_board": "CBSE",
            "board_exam_window": "2027-02-15/2027-03-20",
            "no_nonessential_disruption": "true",
        },
        original_text=(
            "Class X board-exam year. Parents are advised to minimise travel and routine "
            "disruption for Class X students from the second term onward; board exams 15 Feb - "
            "20 Mar 2027."
        ),
    )
    priya_travel = Constraint(
        id=CONSTRAINT_PRIYA_TRAVEL,
        provenance=prov(source_document_id=_DOC_TRAVEL, region="itinerary-block", confidence=0.96),
        kind=ConstraintKind.SCHEDULE,
        severity=ConstraintSeverity.HARD,
        validity_start=datetime(2026, 9, 2, tzinfo=NOW.tzinfo),
        validity_end=datetime(2026, 9, 4, 23, 59, tzinfo=NOW.tzinfo),
        structured={
            "days_of_week": "daily",
            "start_time": "00:00",
            "end_time": "23:59",
            "reason": "work_travel",
        },
        original_text=(
            "Priya is in Bengaluru for the quarterly review 2-4 September; back on the red-eye "
            "night of the 4th."
        ),
    )
    nodes += [dadi_mobility, dadi_bp_meds, aarav_boardexam, priya_travel]

    edges += [
        edge(
            "e-fd-constrains-mobility-dadi",
            EdgeType.CONSTRAINS,
            CONSTRAINT_DADI_MOBILITY,
            PERSON_DADI,
            source_document_id=_DOC_MOBILITY,
            confidence=0.95,
        ),
        edge(
            "e-fd-constrains-bpmeds-dadi",
            EdgeType.CONSTRAINS,
            CONSTRAINT_DADI_BP_MEDS,
            PERSON_DADI,
            source_document_id=_DOC_MEDS,
            confidence=0.94,
        ),
        edge(
            "e-fd-constrains-boardexam-aarav",
            EdgeType.CONSTRAINS,
            CONSTRAINT_AARAV_BOARDEXAM,
            PERSON_AARAV,
            source_document_id=_DOC_BOARDEXAM,
            confidence=0.93,
        ),
        edge(
            "e-fd-constrains-travel-priya",
            EdgeType.CONSTRAINS,
            CONSTRAINT_PRIYA_TRAVEL,
            PERSON_PRIYA,
            source_document_id=_DOC_TRAVEL,
            confidence=0.96,
        ),
    ]

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

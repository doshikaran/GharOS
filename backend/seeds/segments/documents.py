"""Segment: the ugly demo documents and everything they extract to
(non-financial). Spec §24 (the 4-minute script) and §26 (demo data).

Covers, live-legible on stage:

* the chaotic **field-trip email** -> six obligations, five of them
  `implied`, each with a provenance edge back to its source span
  (spec §24 0:40-1:40 / demo-beat "five implied obligations");
* the **nut-allergy vs Tuesday's canteen menu** hard conflict (a red
  `violates` + `conflicts_with` edge onto the frozen base
  `constraint-nut-free`);
* the **temporal collision** — Ananya's 1:30 PM half-day pickup vs
  Priya's 1:00 PM meeting — as a `conflicts_with` edge;
* the **handwritten attendance register** for the second staff member
  (Salim) -> a real `AttendanceRecord` + `attendance_of` edge (the demo
  seed's version of DEBT-004's path; the through-`POST /ingest` proof is
  `backend/tests/test_attendance_register_ingest_wire.py`);
* the **deliberately ambiguous permission slip** — "A. Sharma", 7B or 4A?
  -> an `AMBIGUOUS`-derivation obligation with *no* owner guessed on a
  hard-constraint-bearing entity, plus a PENDING `ApprovalRequest`
  (spec §24 3:05-3:25, the exception beat).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from contracts.graph_types import (
    ApprovalRequest,
    ApprovalStatus,
    AttendanceRecord,
    Derivation,
    Edge,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Provenance,
    SourceDocument,
)

from ._common import NOW, Segment, ambiguous_prov, edge, prov
from .roster import (
    CONSTRAINT_AARAV_BOARDEXAM,
    CONSTRAINT_DADI_MOBILITY,
    CONSTRAINT_PRIYA_TRAVEL,
    PERSON_ANANYA,
    PERSON_DADI,
    PERSON_MAYA,
    PERSON_PRIYA,
    PERSON_ROHAN,
    PERSON_SALIM,
)

CONSTRAINT_NUT_FREE = NodeId("constraint-nut-free")  # frozen base id

DOC_FIELDTRIP = "doc-fieldtrip-email"
DOC_SCHOOL_NOTICES = "doc-school-notices"
DOC_PRIYA_CALENDAR = "doc-priya-calendar-invite"
DOC_SOCIETY_SEPT = "doc-society-notice-sept"
DOC_MAYA_LEAVE = "doc-maya-leave-whatsapp"
DOC_SALIM_REGISTER = "doc-salim-register-aug"
DOC_CARDIOLOGY = "doc-dadi-cardiology-letter"
DOC_PHYSIO = "doc-dadi-physio-discharge-summary"
DOC_BOARDEXAM = "doc-greenfield-board-exam-circular"
DOC_TRAVEL = "doc-priya-travel-itinerary-email"
DOC_AMBIGUOUS_SLIP = "doc-ambiguous-permission-slip"

OBLIGATION_FIELDTRIP_FEE = NodeId("obligation-fd-fieldtrip-fee")
OBLIGATION_MAINTENANCE_SEPT = NodeId("obligation-fd-maintenance-sept")
OBLIGATION_SALIM_SALARY = NodeId("obligation-fd-salim-salary")
ATTENDANCE_SALIM_AUG = NodeId("attendance-salim-2026-08")

_SEP = datetime(2026, 9, 1, tzinfo=NOW.tzinfo)


def _sep(day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=NOW.tzinfo)


def _doc(
    doc_id: str,
    *,
    channel: str,
    raw_payload_ref: str,
    document_type: str,
    language: str,
    ingested_days_ago: float,
) -> SourceDocument:
    return SourceDocument(
        id=NodeId(doc_id),
        provenance=prov(source_document_id=doc_id, region="whole-document", confidence=0.9),
        channel=channel,
        raw_payload_ref=raw_payload_ref,
        document_type=document_type,
        ingested_at=NOW - timedelta(days=ingested_days_ago),
        original_language=language,
    )


def _obl(
    obl_id: str,
    *,
    title: str,
    obligation_type: str,
    due_at: datetime | None,
    effort_minutes: int,
    status: ObligationStatus,
    derivation: ObligationDerivation,
    provenance: Provenance,
    must_start_by: datetime | None = None,
) -> Obligation:
    return Obligation(
        id=NodeId(obl_id),
        provenance=provenance,
        title=title,
        obligation_type=obligation_type,
        due_at=due_at,
        must_start_by=must_start_by,
        effort_estimate_minutes=effort_minutes,
        status=status,
        stated_or_implied=derivation,
    )


def build() -> Segment:  # noqa: C901 - a flat data manifest, not branching logic
    nodes: list[object] = []
    edges: list[Edge] = []

    # -- source documents --------------------------------------------------
    docs = [
        _doc(
            DOC_FIELDTRIP,
            channel="whatsapp",
            raw_payload_ref="chats/greenfield-7b-parents-2026-08-28.jpg",
            document_type="school_communication",
            language="hi",
            ingested_days_ago=2,
        ),
        _doc(
            DOC_SCHOOL_NOTICES,
            channel="upload",
            raw_payload_ref="scans/greenfield-weekly-circular-wk36.pdf",
            document_type="school_communication",
            language="en",
            ingested_days_ago=3,
        ),
        _doc(
            DOC_PRIYA_CALENDAR,
            channel="email",
            raw_payload_ref="emails/fwd-quarterly-planning-invite.eml",
            document_type="chat_thread",
            language="en",
            ingested_days_ago=3,
        ),
        _doc(
            DOC_SOCIETY_SEPT,
            channel="upload",
            raw_payload_ref="scans/sunrise-society-maintenance-sept-2026.jpg",
            document_type="society_notice",
            language="en",
            ingested_days_ago=6,
        ),
        _doc(
            DOC_MAYA_LEAVE,
            channel="whatsapp",
            raw_payload_ref="chats/maya-bai-2026-08-27.jpg",
            document_type="chat_thread",
            language="hi",
            ingested_days_ago=3,
        ),
        _doc(
            DOC_SALIM_REGISTER,
            channel="upload",
            raw_payload_ref="registers/salim-attendance-2026-08.jpg",
            document_type="attendance_register",
            language="hi",
            ingested_days_ago=1,
        ),
        _doc(
            DOC_CARDIOLOGY,
            channel="upload",
            raw_payload_ref="scans/dadi-cardiology-opd-note-2026-08.pdf",
            document_type="medical_document",
            language="en",
            ingested_days_ago=8,
        ),
        _doc(
            DOC_PHYSIO,
            channel="upload",
            raw_payload_ref="scans/dadi-physio-discharge-2026-07.pdf",
            document_type="medical_document",
            language="en",
            ingested_days_ago=40,
        ),
        _doc(
            DOC_BOARDEXAM,
            channel="email",
            raw_payload_ref="emails/greenfield-classX-boardyear-circular.eml",
            document_type="school_communication",
            language="en",
            ingested_days_ago=25,
        ),
        _doc(
            DOC_TRAVEL,
            channel="email",
            raw_payload_ref="emails/indigo-itinerary-blr-2026-09.eml",
            document_type="chat_thread",
            language="en",
            ingested_days_ago=5,
        ),
        _doc(
            DOC_AMBIGUOUS_SLIP,
            channel="upload",
            raw_payload_ref="scans/swimming-gala-consent-form-photo.jpg",
            document_type="permission_slip",
            language="hi",
            ingested_days_ago=1,
        ),
    ]
    nodes += docs

    # -- field-trip email: 1 stated + 5 implied obligations ---------------
    fee = _obl(
        str(OBLIGATION_FIELDTRIP_FEE),
        title="Pay Aarav's museum field-trip fee (INR 850)",
        obligation_type="payment",
        due_at=_sep(5, 17),
        effort_minutes=10,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.STATED,
        provenance=prov(source_document_id=DOC_FIELDTRIP, region="para-2-line-3", confidence=0.95),
    )
    slip = _obl(
        "obligation-fd-fieldtrip-slip",
        title="Sign and return Aarav's field-trip permission slip",
        obligation_type="admin",
        due_at=_sep(9, 15),
        effort_minutes=10,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_FIELDTRIP,
            region="para-2-line-1",
            derivation=Derivation.INFERRED,
            confidence=0.86,
        ),
    )
    lunch = _obl(
        "obligation-fd-fieldtrip-lunch",
        title="Pack Aarav a nut-free packed lunch for the field trip (Fri 12 Sep)",
        obligation_type="errand",
        due_at=_sep(12, 7),
        effort_minutes=20,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_FIELDTRIP,
            region="para-3-line-2",
            derivation=Derivation.INFERRED,
            confidence=0.82,
        ),
    )
    dropoff = _obl(
        "obligation-fd-fieldtrip-dropoff",
        title="Drop Aarav at school by 7:15 AM for the early field-trip departure (Fri 12 Sep)",
        obligation_type="errand",
        due_at=_sep(12, 7, 15),
        effort_minutes=30,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_FIELDTRIP,
            region="para-3-line-1",
            derivation=Derivation.INFERRED,
            confidence=0.84,
        ),
    )
    idcopy = _obl(
        "obligation-fd-fieldtrip-idcopy",
        title="Send a photocopy of Aarav's ID for the museum entry list",
        obligation_type="admin",
        due_at=_sep(9, 15),
        effort_minutes=10,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_FIELDTRIP,
            region="para-2-line-5",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
    )
    raincoat = _obl(
        "obligation-fd-fieldtrip-raincoat",
        title="Send a raincoat and a labelled water bottle with Aarav on trip day",
        obligation_type="errand",
        due_at=_sep(12, 7),
        effort_minutes=10,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_FIELDTRIP,
            region="para-4-line-1",
            derivation=Derivation.INFERRED,
            confidence=0.78,
        ),
    )
    fieldtrip_obls = [fee, slip, lunch, dropoff, idcopy, raincoat]
    nodes += fieldtrip_obls

    edges.append(
        edge(
            "e-fd-states-fieldtrip-fee",
            EdgeType.STATES,
            NodeId(DOC_FIELDTRIP),
            fee.id,
            source_document_id=DOC_FIELDTRIP,
            region="para-2-line-3",
            derivation=Derivation.EXTRACTED,
        )
    )
    for obl in (slip, lunch, dropoff, idcopy, raincoat):
        edges.append(
            edge(
                f"e-fd-implies-{obl.id}",
                EdgeType.IMPLIES,
                NodeId(DOC_FIELDTRIP),
                obl.id,
                source_document_id=DOC_FIELDTRIP,
                region="body",
            )
        )
    for obl in fieldtrip_obls:
        edges.append(
            edge(
                f"e-fd-benefits-{obl.id}-aarav",
                EdgeType.BENEFITS,
                obl.id,
                NodeId("person-aarav"),
                source_document_id=DOC_FIELDTRIP,
            )
        )
    for obl, owner in (
        (fee, PERSON_PRIYA),
        (slip, PERSON_ROHAN),
        (lunch, PERSON_PRIYA),
        (dropoff, PERSON_ROHAN),
        (idcopy, PERSON_ROHAN),
        (raincoat, PERSON_PRIYA),
    ):
        edges.append(
            edge(f"e-fd-owned-{obl.id}", EdgeType.OWNED_BY, obl.id, owner, source_document_id=DOC_FIELDTRIP)
        )

    # -- nut-allergy vs Tuesday canteen menu (the red conflict) ----------
    canteen = _obl(
        "obligation-fd-canteen-tuesday-lunch",
        title="Aarav's Tuesday school lunch is the canteen set menu (peanut-chikki dessert listed)",
        obligation_type="care",
        due_at=_sep(9, 12, 30),
        effort_minutes=0,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.STATED,
        provenance=prov(source_document_id=DOC_SCHOOL_NOTICES, region="menu-table-tuesday", confidence=0.88),
    )
    pack_tue = _obl(
        "obligation-fd-pack-lunch-tuesday",
        title="Pack Aarav a nut-free lunch on Tuesday instead of the canteen menu",
        obligation_type="errand",
        due_at=_sep(9, 7, 30),
        effort_minutes=15,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_SCHOOL_NOTICES,
            region="menu-table-tuesday",
            derivation=Derivation.INFERRED,
            confidence=0.83,
        ),
    )
    nodes += [canteen, pack_tue]
    edges += [
        edge(
            "e-fd-states-canteen",
            EdgeType.STATES,
            NodeId(DOC_SCHOOL_NOTICES),
            canteen.id,
            source_document_id=DOC_SCHOOL_NOTICES,
            region="menu-table",
            derivation=Derivation.EXTRACTED,
        ),
        edge(
            "e-fd-implies-pack-tue",
            EdgeType.IMPLIES,
            NodeId(DOC_SCHOOL_NOTICES),
            pack_tue.id,
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-violates-canteen-nutfree",
            EdgeType.VIOLATES,
            canteen.id,
            CONSTRAINT_NUT_FREE,
            source_document_id=DOC_SCHOOL_NOTICES,
            region="menu-table-tuesday",
            derivation=Derivation.INFERRED,
            confidence=0.9,
        ),
        edge(
            "e-fd-conflicts-canteen-nutfree",
            EdgeType.CONFLICTS_WITH,
            canteen.id,
            CONSTRAINT_NUT_FREE,
            source_document_id=DOC_SCHOOL_NOTICES,
            region="menu-table-tuesday",
            derivation=Derivation.INFERRED,
            confidence=0.9,
        ),
        edge(
            "e-fd-benefits-canteen-aarav",
            EdgeType.BENEFITS,
            canteen.id,
            NodeId("person-aarav"),
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-benefits-packtue-aarav",
            EdgeType.BENEFITS,
            pack_tue.id,
            NodeId("person-aarav"),
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-owned-packtue",
            EdgeType.OWNED_BY,
            pack_tue.id,
            PERSON_PRIYA,
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
    ]

    # -- temporal collision: 1:30 pickup vs 1:00 meeting ----------------
    pickup_ananya = _obl(
        "obligation-fd-pickup-ananya",
        title="Pick up Ananya from school at 1:30 PM Tuesday 9 Sep (half day)",
        obligation_type="errand",
        due_at=_sep(9, 13, 30),
        effort_minutes=40,
        must_start_by=_sep(9, 13, 10),
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_SCHOOL_NOTICES,
            region="half-day-notice",
            derivation=Derivation.INFERRED,
            confidence=0.85,
        ),
    )
    priya_meeting = _obl(
        "obligation-fd-priya-meeting",
        title="Priya: quarterly planning meeting 1:00-2:00 PM Tuesday 9 Sep",
        obligation_type="work",
        due_at=_sep(9, 13, 0),
        effort_minutes=60,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.STATED,
        provenance=prov(source_document_id=DOC_PRIYA_CALENDAR, region="invite-when-line", confidence=0.94),
    )
    nodes += [pickup_ananya, priya_meeting]
    edges += [
        edge(
            "e-fd-implies-pickup-ananya",
            EdgeType.IMPLIES,
            NodeId(DOC_SCHOOL_NOTICES),
            pickup_ananya.id,
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-states-priya-meeting",
            EdgeType.STATES,
            NodeId(DOC_PRIYA_CALENDAR),
            priya_meeting.id,
            source_document_id=DOC_PRIYA_CALENDAR,
            region="invite-when-line",
            derivation=Derivation.EXTRACTED,
        ),
        edge(
            "e-fd-owned-pickup-ananya",
            EdgeType.OWNED_BY,
            pickup_ananya.id,
            PERSON_PRIYA,
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-benefits-pickup-ananya",
            EdgeType.BENEFITS,
            pickup_ananya.id,
            PERSON_ANANYA,
            source_document_id=DOC_SCHOOL_NOTICES,
        ),
        edge(
            "e-fd-owned-priya-meeting",
            EdgeType.OWNED_BY,
            priya_meeting.id,
            PERSON_PRIYA,
            source_document_id=DOC_PRIYA_CALENDAR,
        ),
        edge(
            "e-fd-conflicts-pickup-meeting",
            EdgeType.CONFLICTS_WITH,
            pickup_ananya.id,
            priya_meeting.id,
            source_document_id=DOC_SCHOOL_NOTICES,
            region="cross-check",
            derivation=Derivation.INFERRED,
            confidence=0.92,
        ),
    ]

    # -- society maintenance (September cycle, price already crept up) ---
    maintenance = _obl(
        str(OBLIGATION_MAINTENANCE_SEPT),
        title="Pay September society maintenance (INR 2,650)",
        obligation_type="payment",
        due_at=_sep(10, 17),
        effort_minutes=10,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.STATED,
        provenance=prov(source_document_id=DOC_SOCIETY_SEPT, region="amount-line", confidence=0.9),
    )
    nodes.append(maintenance)
    edges += [
        edge(
            "e-fd-states-maintenance-sept",
            EdgeType.STATES,
            NodeId(DOC_SOCIETY_SEPT),
            maintenance.id,
            source_document_id=DOC_SOCIETY_SEPT,
            region="amount-line",
            derivation=Derivation.EXTRACTED,
        ),
        edge(
            "e-fd-owned-maintenance-sept",
            EdgeType.OWNED_BY,
            maintenance.id,
            PERSON_PRIYA,
            source_document_id=DOC_SOCIETY_SEPT,
        ),
    ]

    # -- Maya's leave (WhatsApp, Hinglish) -----------------------------
    maya_cover = _obl(
        "obligation-fd-maya-cover",
        title="Arrange household cover for Maya's leave, 15-17 Sep",
        obligation_type="staffing",
        due_at=_sep(14, 18),
        effort_minutes=30,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_MAYA_LEAVE, region="msg-4", derivation=Derivation.INFERRED, confidence=0.8
        ),
    )
    nodes.append(maya_cover)
    edges += [
        edge(
            "e-fd-implies-maya-cover",
            EdgeType.IMPLIES,
            NodeId(DOC_MAYA_LEAVE),
            maya_cover.id,
            source_document_id=DOC_MAYA_LEAVE,
        ),
        edge(
            "e-fd-owned-maya-cover",
            EdgeType.OWNED_BY,
            maya_cover.id,
            PERSON_PRIYA,
            source_document_id=DOC_MAYA_LEAVE,
        ),
        edge(
            "e-fd-benefits-maya-cover",
            EdgeType.BENEFITS,
            maya_cover.id,
            PERSON_MAYA,
            source_document_id=DOC_MAYA_LEAVE,
        ),
    ]

    # -- Salim's handwritten attendance register -> AttendanceRecord ----
    attendance_salim = AttendanceRecord(
        id=ATTENDANCE_SALIM_AUG,
        provenance=prov(
            source_document_id=DOC_SALIM_REGISTER,
            region="grid",
            derivation=Derivation.EXTRACTED,
            confidence=0.93,
        ),
        staff_person_id=PERSON_SALIM,
        month="2026-08",
        days_present=24,
        days_absent=1,
        days_on_leave=1,
        total_days_in_period=26,
        daily_marks={
            "01": "present",
            "02": "present",
            "03": "present",
            "04": "absent",
            "05": "present",
            "06": "leave",
            "07": "present",
            "08": "present",
        },
        advance_notations=("hasil 3000 - 14 tarikh (margin, blue ink)",),
    )
    salim_salary = _obl(
        str(OBLIGATION_SALIM_SALARY),
        title="Pay Salim's August salary",
        obligation_type="payment",
        due_at=_sep(3, 12),
        effort_minutes=5,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_SALIM_REGISTER,
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.82,
        ),
    )
    nodes += [attendance_salim, salim_salary]
    edges += [
        edge(
            "e-fd-attendance_of-salim",
            EdgeType.ATTENDANCE_OF,
            ATTENDANCE_SALIM_AUG,
            PERSON_SALIM,
            source_document_id=DOC_SALIM_REGISTER,
            region="name-header",
            derivation=Derivation.EXTRACTED,
            confidence=0.93,
        ),
        edge(
            "e-fd-implies-salim-salary",
            EdgeType.IMPLIES,
            NodeId(DOC_SALIM_REGISTER),
            salim_salary.id,
            source_document_id=DOC_SALIM_REGISTER,
        ),
        edge(
            "e-fd-owned-salim-salary",
            EdgeType.OWNED_BY,
            salim_salary.id,
            PERSON_PRIYA,
            source_document_id=DOC_SALIM_REGISTER,
        ),
        edge(
            "e-fd-benefits-salim-salary",
            EdgeType.BENEFITS,
            salim_salary.id,
            PERSON_SALIM,
            source_document_id=DOC_SALIM_REGISTER,
        ),
    ]

    # -- medical documents (OCR-noisy) --------------------------------
    cardio_followup = _obl(
        "obligation-fd-dadi-cardio-followup",
        title="Book Dadi's cardiology follow-up (advised in 6 weeks)",
        obligation_type="medical",
        due_at=NOW + timedelta(days=42),
        effort_minutes=20,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_CARDIOLOGY,
            region="plan-line-2",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
    )
    walker_service = _obl(
        "obligation-fd-dadi-walker-service",
        title="Service Dadi's wheeled walker (brake wear flagged at physio discharge)",
        obligation_type="errand",
        due_at=_sep(20, 12),
        effort_minutes=45,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_PHYSIO,
            region="equipment-note",
            derivation=Derivation.INFERRED,
            confidence=0.75,
        ),
    )
    nodes += [cardio_followup, walker_service]
    edges += [
        edge(
            "e-fd-implies-cardio-followup",
            EdgeType.IMPLIES,
            NodeId(DOC_CARDIOLOGY),
            cardio_followup.id,
            source_document_id=DOC_CARDIOLOGY,
        ),
        edge(
            "e-fd-owned-cardio-followup",
            EdgeType.OWNED_BY,
            cardio_followup.id,
            PERSON_ROHAN,
            source_document_id=DOC_CARDIOLOGY,
        ),
        edge(
            "e-fd-benefits-cardio-followup",
            EdgeType.BENEFITS,
            cardio_followup.id,
            PERSON_DADI,
            source_document_id=DOC_CARDIOLOGY,
        ),
        edge(
            "e-fd-implies-walker-service",
            EdgeType.IMPLIES,
            NodeId(DOC_PHYSIO),
            walker_service.id,
            source_document_id=DOC_PHYSIO,
        ),
        edge(
            "e-fd-owned-walker-service",
            EdgeType.OWNED_BY,
            walker_service.id,
            PERSON_ROHAN,
            source_document_id=DOC_PHYSIO,
        ),
        edge(
            "e-fd-benefits-walker-service",
            EdgeType.BENEFITS,
            walker_service.id,
            PERSON_DADI,
            source_document_id=DOC_PHYSIO,
        ),
        edge(
            "e-fd-violates-walker-mobility",
            EdgeType.VIOLATES,
            walker_service.id,
            CONSTRAINT_DADI_MOBILITY,
            source_document_id=DOC_PHYSIO,
            region="equipment-note",
            derivation=Derivation.INFERRED,
            confidence=0.6,
        ),
    ]

    # -- board-exam circular + travel itinerary ----------------------
    study_plan = _obl(
        "obligation-fd-aarav-study-plan",
        title="Set up Aarav's board-exam study schedule and limit weekend disruptions",
        obligation_type="planning",
        due_at=_sep(15, 20),
        effort_minutes=90,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_BOARDEXAM, region="para-2", derivation=Derivation.INFERRED, confidence=0.72
        ),
    )
    cover_priya_runs = _obl(
        "obligation-fd-cover-priya-runs",
        title="Cover Priya's school run and errands 2-4 Sep (she is in Bengaluru)",
        obligation_type="errand",
        due_at=_sep(2, 8),
        effort_minutes=60,
        status=ObligationStatus.ASSIGNED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=prov(
            source_document_id=DOC_TRAVEL,
            region="itinerary-block",
            derivation=Derivation.INFERRED,
            confidence=0.83,
        ),
    )
    nodes += [study_plan, cover_priya_runs]
    edges += [
        edge(
            "e-fd-implies-study-plan",
            EdgeType.IMPLIES,
            NodeId(DOC_BOARDEXAM),
            study_plan.id,
            source_document_id=DOC_BOARDEXAM,
        ),
        edge(
            "e-fd-owned-study-plan",
            EdgeType.OWNED_BY,
            study_plan.id,
            PERSON_PRIYA,
            source_document_id=DOC_BOARDEXAM,
        ),
        edge(
            "e-fd-benefits-study-plan",
            EdgeType.BENEFITS,
            study_plan.id,
            NodeId("person-aarav"),
            source_document_id=DOC_BOARDEXAM,
        ),
        edge(
            "e-fd-violates-studyplan-boardexam",
            EdgeType.VIOLATES,
            study_plan.id,
            CONSTRAINT_AARAV_BOARDEXAM,
            source_document_id=DOC_BOARDEXAM,
            region="para-2",
            derivation=Derivation.INFERRED,
            confidence=0.55,
        ),
        edge(
            "e-fd-implies-cover-priya-runs",
            EdgeType.IMPLIES,
            NodeId(DOC_TRAVEL),
            cover_priya_runs.id,
            source_document_id=DOC_TRAVEL,
        ),
        edge(
            "e-fd-owned-cover-priya-runs",
            EdgeType.OWNED_BY,
            cover_priya_runs.id,
            PERSON_ROHAN,
            source_document_id=DOC_TRAVEL,
        ),
        edge(
            "e-fd-benefits-cover-priya-runs",
            EdgeType.BENEFITS,
            cover_priya_runs.id,
            PERSON_PRIYA,
            source_document_id=DOC_TRAVEL,
        ),
        edge(
            "e-fd-depends-cover-on-travel",
            EdgeType.VIOLATES,
            cover_priya_runs.id,
            CONSTRAINT_PRIYA_TRAVEL,
            source_document_id=DOC_TRAVEL,
            region="itinerary-block",
            derivation=Derivation.INFERRED,
            confidence=0.5,
        ),
    ]

    # -- the deliberately ambiguous permission slip (the exception beat)
    ambiguous_consent = _obl(
        "obligation-fd-ambiguous-consent",
        title="Sign the inter-school swimming-gala consent form for 'A. Sharma' (class 7B or 4A?)",
        obligation_type="admin",
        due_at=_sep(11, 15),
        effort_minutes=10,
        status=ObligationStatus.DERIVED,
        derivation=ObligationDerivation.IMPLIED,
        provenance=ambiguous_prov(
            source_document_id=DOC_AMBIGUOUS_SLIP, region="name-field", confidence=0.35
        ),
    )
    escalation = ApprovalRequest(
        id=NodeId("approval-fd-ambiguous-escalation"),
        provenance=prov(
            source_document_id=DOC_AMBIGUOUS_SLIP,
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.35,
        ),
        proposed_action_summary=(
            "Escalate to a human: the swimming-gala consent form names 'A. Sharma' with no class "
            "or DOB. It could be Aarav (7B) or Ananya (4A). Both carry a hard nut-free / medical "
            "context, so the system will not guess the child on a hard-constraint-bearing entity."
        ),
        evidence_bundle={
            "candidates": "person-aarav (7B), person-ananya (4A)",
            "missing_fields": "class, date_of_birth",
            "source_document": DOC_AMBIGUOUS_SLIP,
        },
        risk_tier="R2",
        confidence=0.35,
        consequence_if_wrong=(
            "The wrong child's dietary/medical details are submitted to an external event organiser."
        ),
        status=ApprovalStatus.PENDING,
        expires_at=NOW + timedelta(days=3),
    )
    nodes += [ambiguous_consent, escalation]
    edges.append(
        edge(
            "e-fd-states-ambiguous-consent",
            EdgeType.STATES,
            NodeId(DOC_AMBIGUOUS_SLIP),
            ambiguous_consent.id,
            source_document_id=DOC_AMBIGUOUS_SLIP,
            region="body",
            derivation=Derivation.AMBIGUOUS,
            confidence=0.35,
        )
    )
    # No owned_by / benefits edge: the agent deliberately does not resolve
    # the child on a hard-constraint-bearing entity (spec §24 exception beat).

    return Segment(nodes=tuple(nodes), edges=tuple(edges))

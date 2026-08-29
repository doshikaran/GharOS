"""Twenty held-out messy documents for A12's honest evaluation (PHASES.md
Phase 4, "The honest evaluation" — `docs/IMPLICATION_BASELINE.md`).

**Held-out, genuinely.** None of this text, none of these scenarios, and
none of this ground truth were copied from or derived from
`backend/tests/test_implication_agent.py`'s fixtures, `backend/tests/golden/`,
or any other suite A12's prompt was written or iterated against. They were
authored fresh for this evaluation, finalised here, and only then run
through `ImplicationAgent.imply` (`implication_eval.py`) — the ground
truth below was written down *before* that first run, not reverse-
engineered from what the model said. If a later iteration of A12's prompt
or `citation_validator.py` gets re-run against this same set (see
`docs/IMPLICATION_BASELINE.md`'s methodology section for whether that
happened), that fact is recorded there honestly: a set stops being
"held-out" in the strict sense the moment it is iterated against, even if
it stays as the fixed scoring corpus.

**What "ground truth" means here.** `ImplicationAgent` is deliberately
scoped to *implied* obligations only — obligations already literally
present in a document are Phase 3's job (A3 Document Extraction), and
A12's own prompt instructs it not to re-derive them. So each
`HeldOutDocument` supplies the literal, stated facts as
`HouseholdContext.stated_obligations` (standing in for what A3 would
already have extracted), exactly as `context.gather_household_context`
would assemble for a real graph — and `ground_truth_implied` is scored
only against what a careful human would derive *beyond* those stated
facts. Two documents (`eval-15`, `eval-20`) deliberately have an EMPTY
`ground_truth_implied` — they are hallucination-rate control cases: a
plain, self-contained document a careful human derives nothing further
from. Any candidate A12 produces for either is, by construction, a
hallucination.

**`GroundTruthObligation.certainty`.** Most ground-truth items here are
`"clear"` — an obligation essentially any careful family member or judge
would agree follows. A handful are marked `"borderline"`: real inferences
this evaluation's own author judged less clear-cut (a live-consequence
implication where a stricter or looser careful-human reading is
defensible either way). Recorded honestly rather than silently folded
into the same bucket as the clear cases — see the gharos-standards skill's
own instruction on partial-credit judgment calls, applied here to the
*ground truth* construction, not just to scoring A12's output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)

from app.agents.consequence.types import HouseholdContext

# ---------------------------------------------------------------------------
# Ground truth / document shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroundTruthObligation:
    """One obligation a careful human would derive from a held-out
    document, beyond what it literally states. Written down before A12
    ever sees the document (module docstring) — this is what
    `implication_eval.py`'s scoring in `docs/IMPLICATION_BASELINE.md`
    compares A12's real candidates against."""

    ground_truth_id: str
    description: str
    expected_citation_hint: str
    """A verbatim substring of the document's `document_text` a careful
    human would point to as the inference's trigger — checked by
    `test_ground_truth_citation_hints_are_real_substrings_of_their_document`
    to really be a substring, so this evaluation cannot silently drift
    from the document it claims to score against."""
    certainty: Literal["clear", "borderline"]


@dataclass(frozen=True, slots=True)
class HeldOutDocument:
    doc_id: str
    title: str
    document_text: str
    household_context: HouseholdContext
    ground_truth_implied: tuple[GroundTruthObligation, ...]
    notes: str = ""


# ---------------------------------------------------------------------------
# Shared synthetic-context builders (not a persistent household — each
# document gets its own independently-constructed People/Constraints/
# Obligations, matching how `context.gather_household_context` would
# assemble a `HouseholdContext` for one real SOURCE_DOCUMENT).
# ---------------------------------------------------------------------------

_CONTEXT_AS_OF = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

_LANGUAGE_PROFILE = LanguageProfile(
    primary_language="en",
    languages_understood=("en", "hi"),
    script_preference="latin",
    code_mixing_profile="hi-en",
    formality_preference="informal",
    literacy_mode=LiteracyMode.BOTH,
)


def _provenance() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("eval-prior-context"), region="0-1"),
        confidence=0.9,
        deriving_agent=AgentId("A3"),
        created_at=_CONTEXT_AS_OF,
    )


def _person(
    node_id: str,
    display_name: str,
    *,
    role: PersonRole = PersonRole.ADULT,
    can_drive: bool = False,
    can_sign: bool = False,
    has_bank_access: bool = False,
    has_medical_proxy: bool = False,
) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=_provenance(),
        display_name=display_name,
        aliases=(),
        role=role,
        can_drive=can_drive,
        can_sign=can_sign,
        has_bank_access=has_bank_access,
        has_medical_proxy=has_medical_proxy,
        contact_channels=(),
        language_profile=_LANGUAGE_PROFILE,
    )


def _constraint(
    node_id: str,
    kind: ConstraintKind,
    severity: ConstraintSeverity,
    original_text: str,
    *,
    structured: dict[str, str] | None = None,
) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=_provenance(),
        kind=kind,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured=structured or {},
        original_text=original_text,
    )


def _obligation(
    node_id: str,
    title: str,
    obligation_type: str,
    *,
    due_at: datetime | None = None,
    status: ObligationStatus = ObligationStatus.ASSIGNED,
    stated_or_implied: ObligationDerivation = ObligationDerivation.STATED,
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance(),
        title=title,
        obligation_type=obligation_type,
        due_at=due_at,
        must_start_by=None,
        effort_estimate_minutes=None,
        status=status,
        stated_or_implied=stated_or_implied,
    )


# ---------------------------------------------------------------------------
# 01 — School Sports Day: signing deadline vs. a parent's travel window
# ---------------------------------------------------------------------------


def _doc_01() -> HeldOutDocument:
    text = (
        "Subject: St. Xavier's Annual Sports Day — Class 4B\n\n"
        "Dear Parents,\n\n"
        "Sports Day is on Saturday, 5th September. All children must wear the "
        "house-colour T-shirt (already issued) and white sports shoes. Please "
        "send back a filled and signed medical-fitness declaration by "
        "Wednesday, 2nd September — no child will be allowed to participate "
        "without it. Children in the 100m relay team must report by 7:30 AM "
        "for warm-up; the regular assembly bell is at 8:15 AM as usual. "
        "Please label all water bottles with your child's name. If it rains, "
        "the event moves indoors and only the outdoor track events get "
        "cancelled.\n\nRegards,\nClass Teacher, 4B"
    )
    people = (
        _person("p01-priya", "Priya", can_sign=True, can_drive=True),
        _person("p01-rohan", "Rohan", can_sign=True, can_drive=True),
        _person("p01-aarav", "Aarav", role=PersonRole.CHILD),
    )
    open_obligations = (
        _obligation(
            "o01-rohan-trip",
            "Rohan away on a work trip Mon 31 Aug through Wed 2 Sept",
            "travel",
            due_at=datetime(2026, 9, 2, tzinfo=UTC),
        ),
        _obligation(
            "o01-carpool",
            "Morning carpool drop-off with the Mehta family at 8:00 AM",
            "routine",
        ),
    )
    stated = (
        _obligation(
            "s01-slip",
            "Send back signed medical-fitness declaration by 2 Sept",
            "permission_slip",
            due_at=datetime(2026, 9, 2, tzinfo=UTC),
        ),
        _obligation("s01-uniform", "Ensure Aarav wears house-colour T-shirt and white shoes", "logistics"),
        _obligation(
            "s01-relay",
            "Report by 7:30 AM for relay warm-up",
            "activity",
            due_at=datetime(2026, 9, 5, 7, 30, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt01-1",
            description=(
                "Rohan (one of the two people who can sign) is away on a work trip through "
                "Wednesday 2 September — the same day the signed declaration is due — so the "
                "declaration must actually be signed before he leaves (by Monday 31 August), "
                "not left until the stated Wednesday deadline."
            ),
            expected_citation_hint="signed medical-fitness declaration by Wednesday, 2nd September",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt01-2",
            description=(
                "The relay team's 7:30 AM report time is earlier than the usual 8:15 AM assembly "
                "and doesn't match the household's existing 8:00 AM carpool drop-off with the "
                "Mehta family — a separate, earlier transport arrangement is needed for Sports Day."
            ),
            expected_citation_hint="report by 7:30 AM for warm-up",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-01-sports-day",
        title="School Sports Day notice — signing deadline vs. parent travel",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 02 — Pediatrician allergy test: fasting window + a fixed meeting clash
# ---------------------------------------------------------------------------


def _doc_02() -> HeldOutDocument:
    text = (
        "Reminder from Dr. Kulkarni's Clinic:\n\n"
        "Aarav's allergy panel blood test is confirmed for Thursday, 27 Aug, "
        "9:00 AM. Please ensure Aarav has NOT eaten or had milk for at least "
        "8 hours before the test — water is fine. Bring the previous "
        "prescription and the insurance card. The clinic is closed for lunch "
        "1-2 PM and results take 3 working days.\n\n- Front desk"
    )
    people = (
        _person("p02-priya", "Priya", can_drive=True, has_bank_access=True),
        _person("p02-rohan", "Rohan", can_drive=True),
        _person("p02-aarav", "Aarav", role=PersonRole.CHILD),
    )
    constraints = (
        _constraint(
            "c02-nut",
            ConstraintKind.DIETARY,
            ConstraintSeverity.HARD,
            "Aarav has a severe nut allergy; no nuts or nut products, ever.",
            structured={"allergen": "nut"},
        ),
    )
    open_obligations = (
        _obligation(
            "o02-meeting",
            "Priya has a fixed 9 AM Thursday client meeting she cannot move",
            "work",
            due_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        ),
    )
    stated = (
        _obligation(
            "s02-test",
            "Take Aarav for allergy blood test, 9 AM Thursday 27 Aug",
            "medical_appointment",
            due_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        ),
        _obligation(
            "s02-fast", "Keep Aarav fasting (no food/milk) for 8 hours before the test", "medical_prep"
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt02-1",
            description=(
                "The 8-hour fasting window has to start the night before — with a 9:00 AM test, "
                "Aarav's dinner and any bedtime milk on Wednesday 26 Aug needs to be finished by "
                "around 1:00 AM at the latest, and no breakfast Thursday morning: a household "
                "routine change nothing here spells out directly."
            ),
            expected_citation_hint="NOT eaten or had milk for at least 8 hours",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt02-2",
            description=(
                "Priya has a fixed 9 AM Thursday client meeting she cannot move — the exact same "
                "time as the test — so Rohan, not Priya, needs to be the one who actually takes "
                "Aarav."
            ),
            expected_citation_hint="9:00 AM",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-02-allergy-test",
        title="Pediatrician appointment — fasting prep + scheduling conflict",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 03 — Society water-tank cleaning: shutoff window collides with routine
# ---------------------------------------------------------------------------


def _doc_03() -> HeldOutDocument:
    text = (
        "NOTICE — Sunrise CHS Ltd.\n\n"
        "Annual overhead tank cleaning is scheduled for Sunday, 30 Aug. Water "
        "supply to all flats will be SHUT OFF from 6:00 AM to 6:00 PM that "
        "day. Residents are advised to store sufficient water in advance. "
        "Cleaning contractors will be on site; please do not use terrace "
        "access that day.\n\n— Secretary, Sunrise CHS"
    )
    people = (
        _person("p03-priya", "Priya", has_bank_access=True),
        _person("p03-rohan", "Rohan"),
        _person("p03-meera", "Meera", role=PersonRole.ELDER),
        _person("p03-sunita", "Sunita", role=PersonRole.STAFF),
    )
    constraints = (
        _constraint(
            "c03-meera-mobility",
            ConstraintKind.MOBILITY,
            ConstraintSeverity.HARD,
            "Meera uses a walker and needs a responsible adult present for her morning routine.",
        ),
    )
    open_obligations = (
        _obligation(
            "o03-cleaning",
            "Sunita's weekly deep-cleaning of the flat, usually done Sunday mornings",
            "household_chore",
        ),
    )
    stated = (
        _obligation(
            "s03-store-water",
            "Store sufficient water in advance of Sunday's 12-hour shutoff",
            "household_chore",
            due_at=datetime(2026, 8, 30, 6, 0, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt03-1",
            description=(
                "Sunita's usual Sunday-morning deep-cleaning (which needs running water) falls "
                "squarely inside the 6 AM-6 PM shutoff window and needs to move to a different "
                "day or time this week."
            ),
            expected_citation_hint="SHUT OFF from 6:00 AM to 6:00 PM",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt03-2",
            description=(
                "Storing water has to actually happen before Sunday 6 AM — Saturday evening at "
                "the latest — given a full 12-hour shutoff starting first thing in the morning, "
                "not 'sometime before Sunday'."
            ),
            expected_citation_hint="store sufficient water in advance",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-03-water-shutoff",
        title="Society water-tank cleaning notice",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 04 — Electricity bill: due date lands on a holiday + a tight budget
# ---------------------------------------------------------------------------


def _doc_04() -> HeldOutDocument:
    text = (
        "CITY POWER CO — ELECTRICITY BILL\n"
        "Acct: 88213-XX | Billing period: 01-Aug-2026 to 31-Aug-2026\n"
        "Units consumed: 410\n"
        "Amount due: Rs 3,850.00\n"
        "Due date: 05-Sep-2026 (Saturday — public holiday, offices closed)\n"
        "Disconnection notice: supply will be disconnected if payment is not "
        "received within 3 days of the due date.\n"
        "Pay online via the CityPower app, UPI, or at any authorised centre."
    )
    people = (
        _person("p04-priya", "Priya", has_bank_access=True),
        _person("p04-rohan", "Rohan", has_bank_access=True),
    )
    constraints = (
        _constraint(
            "c04-budget",
            ConstraintKind.FINANCIAL,
            ConstraintSeverity.SOFT,
            "Household is tracking a tight monthly budget this quarter; large amounts need advance planning.",
        ),
    )
    stated = (
        _obligation(
            "s04-pay",
            "Pay electricity bill of Rs 3,850 by 5 Sept",
            "payment",
            due_at=datetime(2026, 9, 5, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt04-1",
            description=(
                "The due date, 5 September, is a Saturday and a public holiday — bank branches "
                "and the authorised centre won't be open — so if not paying via app/UPI, the "
                "payment needs to happen by Friday 4 Sept instead of the printed due date."
            ),
            expected_citation_hint="05-Sep-2026 (Saturday — public holiday, offices closed)",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt04-2",
            description=(
                "Rs 3,850 is a larger-than-routine amount against a household tracking a tight "
                "budget this quarter — worth checking against available funds ahead of the due "
                "date rather than assuming it's available."
            ),
            expected_citation_hint="Amount due: Rs 3,850.00",
            certainty="borderline",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-04-electricity-bill",
        title="Electricity bill — due date on a holiday + tight budget",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=(),
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 05 — Vet rabies booster: shared "before Friday" trigger, two implications
# ---------------------------------------------------------------------------


def _doc_05() -> HeldOutDocument:
    text = (
        "Happy Paws Veterinary Clinic\n\n"
        "Reminder: Bruno (Golden Retriever, Reg# HP-2291) is due for his "
        "annual rabies booster this week — please book a slot before Friday. "
        "Bruno should not eat for 2 hours before the vaccination. Booking "
        "window: Mon-Fri, 10 AM-5 PM, walk-ins also accepted but slower.\n\n"
        "Call 022-4455-XXXX or book via our app."
    )
    people = (_person("p05-priya", "Priya"), _person("p05-rohan", "Rohan"))
    open_obligations = (
        _obligation(
            "o05-trip",
            "Family trip to Goa, leaving Friday evening this week",
            "travel",
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt05-1",
            description=(
                "The booking window closes Friday and the family leaves for Goa Friday evening — "
                "the booster needs to happen earlier in the week, not left until the last "
                "bookable day, so it doesn't clash with trip-departure preparation."
            ),
            expected_citation_hint="before Friday",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt05-2",
            description=(
                "With the household away on the Goa trip starting Friday evening, boarding or a "
                "pet-sitter needs to be arranged for Bruno for the days they're gone — a need "
                "this reminder never mentions but that scheduling the booster around the trip "
                "creates."
            ),
            expected_citation_hint="before Friday",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-05-vet-reminder",
        title="Vet rabies booster reminder — travel-week conflict",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=(),
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 06 — Car insurance renewal: PUC prerequisite + sole capable driver
# ---------------------------------------------------------------------------


def _doc_06() -> HeldOutDocument:
    text = (
        "SafeDrive Insurance — Renewal Notice\n\n"
        "Your comprehensive car policy (Reg: MH-04-XX-1234) expires on "
        "10-Sep-2026. Renewal premium: Rs 18,400. Note: as per current "
        "regulations, a valid Pollution Under Control (PUC) certificate is "
        "required at the time of renewal — policies cannot be issued without "
        "one. Your last PUC certificate on file expired 15-Aug-2026.\n\n"
        "Renew online at safedrive.in or call your agent."
    )
    people = (
        _person("p06-rohan", "Rohan", can_drive=True, has_bank_access=True),
        _person("p06-priya", "Priya", can_drive=False, has_bank_access=True),
    )
    open_obligations = (
        _obligation(
            "o06-checkup",
            "Drive Meera to her cardiology check-up next Tuesday",
            "errand",
        ),
    )
    stated = (
        _obligation(
            "s06-renew",
            "Renew car insurance before 10 Sept, pay Rs 18,400",
            "payment",
            due_at=datetime(2026, 9, 10, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt06-1",
            description=(
                "The PUC certificate on file expired 15 Aug and a valid one is required before "
                "the insurance can even be renewed — the car needs to be re-tested for a fresh "
                "PUC certificate before renewal can happen at all, not just before paying the "
                "premium."
            ),
            expected_citation_hint="certificate is required at the time of renewal",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt06-2",
            description=(
                "Rohan is the only capable driver in the household and the policy expires 10 "
                "Sept — since renewal now depends on first getting a fresh PUC, that whole chain "
                "needs to finish before Tuesday's drive to Meera's cardiology check-up, not just "
                "before the bare expiry date."
            ),
            expected_citation_hint="expires on 10-Sep-2026",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-06-car-insurance",
        title="Car insurance renewal — PUC prerequisite + sole driver",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 07 — Landlord notice: rent increase + inspection needing someone home
# ---------------------------------------------------------------------------


def _doc_07() -> HeldOutDocument:
    text = (
        "Dear Tenant,\n\n"
        "This is to inform you that with effect from 1st October, the "
        "monthly rent for Flat 302 will increase to Rs 42,000 (from Rs "
        "38,000) as per the lease renewal clause. Also, our maintenance team "
        "will conduct the annual fittings inspection on Tuesday, 1 Sept, "
        "between 11 AM and 1 PM. Please ensure someone is available to let "
        "them in.\n\nRegards,\nLandlord"
    )
    people = (
        _person("p07-priya", "Priya", has_bank_access=True),
        _person("p07-rohan", "Rohan", has_bank_access=True),
    )
    open_obligations = (
        _obligation(
            "o07-travel",
            "Rohan traveling for work Mon 31 Aug through Wed 2 Sept",
            "travel",
            due_at=datetime(2026, 9, 2, tzinfo=UTC),
        ),
    )
    stated = (
        _obligation(
            "s07-inspection",
            "Be available for maintenance inspection Tue 1 Sept 11 AM-1 PM",
            "logistics",
            due_at=datetime(2026, 9, 1, 11, 0, tzinfo=UTC),
        ),
        _obligation(
            "s07-rent",
            "Rent increases to Rs 42,000 from 1 Oct",
            "payment",
            due_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt07-1",
            description=(
                "Priya works fixed office hours with no WFH flexibility noted and Rohan is "
                "traveling Mon 31 Aug through Wed 2 Sept — exactly covering the Tuesday 1 Sept "
                "inspection window — so neither adult is actually free to let the inspector in; "
                "coverage needs to be arranged rather than assumed."
            ),
            expected_citation_hint="annual fittings inspection on Tuesday, 1 Sept, between 11 AM and 1 PM",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt07-2",
            description=(
                "The rent increasing to Rs 42,000 from 1 October means any existing bank standing "
                "instruction set up for the old Rs 38,000 rent needs to be updated before the "
                "October payment, or it will go out short."
            ),
            expected_citation_hint="monthly rent for Flat 302 will increase to Rs 42,000",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-07-landlord-inspection",
        title="Landlord notice — rent increase + inspection needing someone home",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 08 — Staff leave request (Hindi-English code-mixed): elder-care gap
# ---------------------------------------------------------------------------


def _doc_08() -> HeldOutDocument:
    text = (
        "Didi, mera bhatije ki shaadi hai gaon mein, mujhe 28 Aug se 30 Aug "
        "tak (3 din) chutti chahiye. Main 31 ko wapas aa jaungi subah tak. "
        "Sorry for short notice, shaadi ka date change ho gaya.\n\n- Sunita"
    )
    people = (
        _person("p08-priya", "Priya"),
        _person("p08-rohan", "Rohan"),
        _person("p08-meera", "Meera", role=PersonRole.ELDER),
        _person("p08-sunita", "Sunita", role=PersonRole.STAFF),
    )
    constraints = (
        _constraint(
            "c08-meera-care",
            ConstraintKind.CUSTODY,
            ConstraintSeverity.HARD,
            (
                "Meera needs a responsible adult or the household staff present during daytime "
                "hours; she cannot be left alone for extended stretches."
            ),
        ),
    )
    stated = (
        _obligation(
            "s08-leave",
            "Grant Sunita leave 28-30 Aug",
            "staff_leave",
            due_at=datetime(2026, 8, 30, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt08-1",
            description=(
                "Sunita normally handles Meera's daytime meals and supervision — with her away "
                "28-30 Aug and Meera's hard constraint against being left alone for extended "
                "stretches, alternate daytime care and cooking coverage needs to be arranged for "
                "exactly those three days, not just the leave itself approved."
            ),
            expected_citation_hint="28 Aug se 30 Aug tak",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-08-sunita-leave",
        title="Staff leave request — elder-care coverage gap",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=(),
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 09 — Bank fraud alert: card blocked, a pending autopay put at risk
# ---------------------------------------------------------------------------


def _doc_09() -> HeldOutDocument:
    text = (
        "ALERT from HDFC Bank: We noticed an unusual transaction of Rs "
        "24,999 on your card ending 7742 at 02:14 AM. As a precaution your "
        "card has been TEMPORARILY BLOCKED. If this was you, call "
        "1800-XXX-XXXX to unblock. If not, no action needed, a new card "
        "will be dispatched in 5-7 working days."
    )
    people = (_person("p09-priya", "Priya", has_bank_access=True), _person("p09-rohan", "Rohan"))
    open_obligations = (
        _obligation(
            "o09-lic",
            "LIC premium autopay (Rs 6,200) scheduled to debit this Friday on card ending 7742",
            "payment",
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt09-1",
            description=(
                "Regardless of whether the Rs 24,999 charge was genuine, the card is now blocked "
                "— and the LIC premium autopay of Rs 6,200 is scheduled to hit that same card "
                "this Friday and will now fail; a backup payment method needs to be arranged "
                "before Friday."
            ),
            expected_citation_hint="TEMPORARILY BLOCKED",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt09-2",
            description=(
                "Someone needs to actually call the number to determine whether the Rs 24,999 "
                "transaction was genuine — the notice is explicitly conditional ('if this was "
                "you... if not...') and doesn't resolve itself."
            ),
            expected_citation_hint="call 1800-XXX-XXXX to unblock",
            certainty="borderline",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-09-bank-fraud-alert",
        title="Bank fraud alert — card blocked, pending autopay at risk",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=(),
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 10 — School PTA fee vs. an earlier costume early-bird deadline
# ---------------------------------------------------------------------------


def _doc_10() -> HeldOutDocument:
    text = (
        "Greenwood International School — Parent Circular\n\n"
        "Annual Day 2026 preparations are underway. Term 2 PTA fee of Rs "
        "1,500 is due by 15 Sept (payable via the parent portal). "
        "Separately, if your child wants a costume for the Annual Day group "
        "dance, kindly fill the costume order form and submit with Rs 350 "
        "by 5 Sept — early-bird orders get priority sizing; orders after 5 "
        "Sept are subject to availability and a Rs 100 rush surcharge."
    )
    people = (_person("p10-priya", "Priya"), _person("p10-aarav", "Aarav", role=PersonRole.CHILD))
    open_obligations = (
        _obligation(
            "o10-rehearsal",
            "Aarav attends Annual Day group-dance rehearsals every Tuesday",
            "activity",
        ),
    )
    stated = (
        _obligation(
            "s10-fee",
            "Pay PTA fee Rs 1,500 by 15 Sept",
            "payment",
            due_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt10-1",
            description=(
                "Aarav is already in the Annual Day group-dance rehearsals, so he is a costume "
                "participant — the costume order (its own earlier 5 Sept deadline, with priority "
                "sizing and no surcharge) needs to be submitted well before the general 15 Sept "
                "PTA fee deadline; handling only the fee would miss the costume window entirely."
            ),
            expected_citation_hint="submit with Rs 350 by 5 Sept",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-10-pta-fee-costume",
        title="PTA annual fee + costume order early-bird deadline",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 11 — Minor's passport renewal: 6-month rule + both-parents requirement
# ---------------------------------------------------------------------------


def _doc_11() -> HeldOutDocument:
    text = (
        "Passport Seva — Renewal Reminder\n\n"
        "Aarav Sharma's passport (No. Z7654321) expires on 14-Jan-2027. "
        "Please note: most countries require at least 6 months' passport "
        "validity remaining for visa issuance and entry. For minors, both "
        "parents/guardians must be present in person at the time of "
        "application submission, or a notarised consent letter from the "
        "absent parent is required.\n\nBook your appointment at "
        "passportindia.gov.in"
    )
    people = (
        _person("p11-priya", "Priya", can_sign=True),
        _person("p11-rohan", "Rohan", can_sign=True),
        _person("p11-aarav", "Aarav", role=PersonRole.CHILD),
    )
    open_obligations = (
        _obligation("o11-trip", "Planned family trip abroad (Singapore) in mid-December", "travel"),
        _obligation(
            "o11-rohan-travel",
            "Rohan has back-to-back business travel most weeks until end of November",
            "travel",
        ),
    )
    stated = (
        _obligation(
            "s11-renew",
            "Renew Aarav's passport before expiry 14 Jan 2027",
            "document_renewal",
            due_at=datetime(2027, 1, 14, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt11-1",
            description=(
                "The passport expires 14 Jan 2027 and the household has a trip abroad planned "
                "for mid-December — under the notice's own 6-months-validity rule, the passport "
                "is already below the safe threshold for that trip; renewal needs to happen well "
                "before December, not whenever, or the trip is at risk."
            ),
            expected_citation_hint="at least 6 months' passport validity remaining",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt11-2",
            description=(
                "Because Aarav is a minor, both parents must be present together at the "
                "application appointment (or Rohan needs to provide a notarised consent letter) "
                "— given Rohan's back-to-back travel until end of November, the appointment needs "
                "to land on one of his rare free windows, or the consent-letter route needs to be "
                "arranged instead."
            ),
            expected_citation_hint="both parents/guardians must be present in person",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-11-passport-renewal",
        title="Minor's passport renewal — 6-month rule + both-parents requirement",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 12 — Elder's new medication: timing conflict with an existing prescription
# ---------------------------------------------------------------------------


def _doc_12() -> HeldOutDocument:
    text = (
        "Dr. Rane's Clinic — Follow-up Note for Meera Joshi\n\n"
        "Starting today, please add Metformin 500mg twice daily WITH FOOD "
        "(breakfast and dinner). Important: this must NOT be taken within 2 "
        "hours of her existing Amlodipine (BP tablet), which she currently "
        "takes right after breakfast. Please monitor for nausea for the "
        "first week and report any dizziness immediately.\n\n- Dr. Rane"
    )
    people = (
        _person("p12-meera", "Meera", role=PersonRole.ELDER),
        _person("p12-sunita", "Sunita", role=PersonRole.STAFF),
        _person("p12-priya", "Priya"),
    )
    constraints = (
        _constraint(
            "c12-amlodipine",
            ConstraintKind.MEDICAL,
            ConstraintSeverity.HARD,
            "Meera takes Amlodipine (BP tablet) right after breakfast, every day, no exceptions.",
            structured={"medication": "amlodipine", "timing": "post-breakfast"},
        ),
    )
    stated = (
        _obligation("s12-metformin", "Start Metformin 500mg twice daily with food", "medical_care"),
        _obligation("s12-monitor", "Monitor Meera for nausea for the first week", "medical_care"),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt12-1",
            description=(
                "The new Metformin can't be taken within 2 hours of the existing Amlodipine, "
                "which is currently taken right after breakfast — since Metformin also needs to "
                "be taken with breakfast, the two can't share that slot as currently scheduled; "
                "Meera's daily medication timing needs to be actively rearranged, not just added "
                "onto the existing routine."
            ),
            expected_citation_hint="must NOT be taken within 2 hours of her existing Amlodipine",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt12-2",
            description=(
                "Sunita is the one who actually prepares Meera's meals and administers her "
                "medication day to day — she needs to be told about the new schedule and the "
                "2-hour spacing rule directly, since this note went to the family, not to her."
            ),
            expected_citation_hint="please add Metformin 500mg twice daily",
            certainty="borderline",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-12-meera-medication",
        title="Elder's new medication — timing conflict with existing prescription",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=(),
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 13 — Relative visiting (Hindi-English): guest room vs. scheduled painting
# ---------------------------------------------------------------------------


def _doc_13() -> HeldOutDocument:
    text = (
        'Text from Meera: "Beta, mera behen Kamala agle Mangalwar se ek '
        "hafte ke liye aa rahi hai humare paas. Please make sure the guest "
        'room is ready, and please tell the painter guys."'
    )
    people = (_person("p13-priya", "Priya"), _person("p13-meera", "Meera", role=PersonRole.ELDER))
    constraints = (
        _constraint(
            "c13-budget",
            ConstraintKind.FINANCIAL,
            ConstraintSeverity.SOFT,
            "Household is tracking a tight monthly budget this quarter.",
        ),
    )
    open_obligations = (
        _obligation(
            "o13-painter",
            "Painter scheduled to repaint the guest room this Tuesday through Thursday",
            "home_maintenance",
        ),
    )
    stated = (
        _obligation(
            "s13-guestroom", "Get guest room ready for Kamala's visit starting next Tuesday", "logistics"
        ),
        _obligation("s13-painters", "Tell the painters", "logistics"),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt13-1",
            description=(
                "The painter is already scheduled to repaint the guest room Tuesday through "
                "Thursday — exactly the days Kamala arrives and the room needs to be ready — the "
                "painting job needs to be rescheduled or moved earlier, not just 'told about', "
                "since a freshly painted, unusable room isn't a ready guest room."
            ),
            expected_citation_hint="guest room is ready",
            certainty="clear",
        ),
        GroundTruthObligation(
            ground_truth_id="gt13-2",
            description=(
                "A week-long guest means extra groceries and meals for that week — worth flagging "
                "given the household's own tight-budget stance."
            ),
            expected_citation_hint="ek hafte ke liye",
            certainty="borderline",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-13-relative-visiting",
        title="Relative visiting — guest room conflicts with scheduled painting",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 14 — Society AGM: proxy-vote deadline lands inside a joint travel window
# ---------------------------------------------------------------------------


def _doc_14() -> HeldOutDocument:
    text = (
        "NOTICE OF ANNUAL GENERAL MEETING — Sunrise CHS Ltd.\n\n"
        "The AGM will be held on Sunday, 6 Sept, 10 AM, in the clubhouse. "
        "Agenda includes election of the new Society Secretary and approval "
        "of the annual maintenance budget. Members unable to attend in "
        "person must submit a signed proxy form (available at the society "
        "office) at least 48 hours before the meeting.\n\n— Secretary, "
        "Sunrise CHS"
    )
    people = (
        _person("p14-priya", "Priya", can_sign=True),
        _person("p14-rohan", "Rohan", can_sign=True),
    )
    open_obligations = (
        _obligation(
            "o14-trip",
            "Family trip, both Priya and Rohan away Fri 4 Sept through Mon 7 Sept",
            "travel",
            due_at=datetime(2026, 9, 7, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt14-1",
            description=(
                "Both adults will be away Fri 4 Sept through Mon 7 Sept, covering the Sunday 6 "
                "Sept AGM entirely — since the proxy form must be submitted at least 48 hours "
                "before the meeting (i.e. by Friday 4 Sept, the day they leave), it needs to be "
                "filled, signed, and dropped off before they leave, not handled later."
            ),
            expected_citation_hint="at least 48 hours before the meeting",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-14-agm-proxy",
        title="Society AGM notice — proxy vote needed, both adults traveling",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=(),
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 15 — Grocery delivery receipt: hallucination-rate CONTROL, zero implied
# ---------------------------------------------------------------------------


def _doc_15() -> HeldOutDocument:
    text = (
        "FreshMart Online — Order Confirmation\n"
        "Order #4521 | Delivered 20-Aug-2026, 6:42 PM\n"
        "Items: Basmati Rice 5kg, Toor Dal 1kg, Milk 1L x2, Bread, Bananas x6\n"
        "Total: Rs 850.00 | Paid via UPI\n"
        "Thank you for shopping with FreshMart!"
    )
    people = (_person("p15-priya", "Priya"),)
    return HeldOutDocument(
        doc_id="eval-15-grocery-receipt",
        title="Grocery delivery receipt — hallucination-rate control (zero implied)",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=(),
            stated_obligations=(),
        ),
        ground_truth_implied=(),
        notes=(
            "Control document: a plain, already-delivered-and-paid grocery receipt carries no "
            "genuine implied obligation. Any obligation A12 produces here is a hallucination by "
            "definition — this specifically probes the failure mode of inventing 'restock' or "
            "'meal planning' busywork from a routine receipt."
        ),
    )


# ---------------------------------------------------------------------------
# 16 — WhatsApp thread (code-mixed): dentist run clashes with tuition
# ---------------------------------------------------------------------------


def _doc_16() -> HeldOutDocument:
    text = (
        "Priya: kal Aarav ka dentist appointment hai 4 baje, tum le jaoge?\n"
        "Rohan: haan le jaunga, but mera 3:30 tak call hai office mein\n"
        "Priya: ok fir thoda late ho sakta hai, dentist ko bata dena\n"
        "Rohan: theek hai. Aur school ko bhi batana padega na jaldi nikalne ke liye?\n"
        "Priya: haan sahi hai"
    )
    people = (
        _person("p16-priya", "Priya"),
        _person("p16-rohan", "Rohan"),
        _person("p16-aarav", "Aarav", role=PersonRole.CHILD),
    )
    open_obligations = (_obligation("o16-tuition", "Aarav's math tuition, daily 4:30-5:30 PM", "activity"),)
    stated = (
        _obligation(
            "s16-dentist",
            "Rohan takes Aarav to dentist tomorrow ~4 PM, may run slightly late",
            "medical_appointment",
        ),
        _obligation("s16-school", "Inform the school so Aarav can leave early", "logistics"),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt16-1",
            description=(
                "The dentist appointment is at 4 PM and may run late since Rohan can't leave "
                "office until 3:30 — but Aarav has math tuition every day 4:30-5:30 PM, which the "
                "dentist visit will very likely overlap; nobody in the chat has connected these "
                "two, and either the tuition slot needs to be skipped/rescheduled that day or the "
                "dentist visit needs tighter timing."
            ),
            expected_citation_hint="thoda late ho sakta hai",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-16-chat-dentist",
        title="WhatsApp thread — dentist pickup clashes with tuition",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 17 — Property tax: an earlier rebate deadline vs. the final due date
# ---------------------------------------------------------------------------


def _doc_17() -> HeldOutDocument:
    text = (
        "Municipal Corporation — Property Tax Demand Notice 2026-27\n\n"
        "Property ID: PT-88213 | Amount Due: Rs 22,400\n"
        "Pay by 30-Sept-2026 to avail 5% early-payment rebate (Rs 1,120 "
        "savings). Final due date without rebate: 31-Dec-2026. Penalty of "
        "2% per month applies after 31-Dec-2026."
    )
    people = (_person("p17-priya", "Priya", has_bank_access=True), _person("p17-rohan", "Rohan"))
    constraints = (
        _constraint(
            "c17-budget",
            ConstraintKind.FINANCIAL,
            ConstraintSeverity.SOFT,
            "Household is tracking a tight monthly budget this quarter.",
        ),
    )
    stated = (
        _obligation(
            "s17-tax",
            "Pay property tax Rs 22,400 by final deadline 31 Dec 2026",
            "payment",
            due_at=datetime(2026, 12, 31, tzinfo=UTC),
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt17-1",
            description=(
                "Paying by 30 Sept instead of waiting until the final 31 Dec deadline saves Rs "
                "1,120 (the 5% rebate) — worth prioritising given the household's tight-budget "
                "stance, and it is a genuinely different, much earlier deadline than the 'final "
                "due date' also listed, easy to default to if not read carefully."
            ),
            expected_citation_hint="5% early-payment rebate (Rs 1,120 savings)",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-17-property-tax",
        title="Property tax — early-payment rebate window",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=(),
            stated_obligations=stated,
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 18 — Appliance free-service camp vs. an already-open complaint
# ---------------------------------------------------------------------------


def _doc_18() -> HeldOutDocument:
    text = (
        "BlueWave Home Appliances\n\n"
        "Free service camp this week only (25-29 Aug) for all BlueWave "
        "washing machines and refrigerators — no service charge, only parts "
        "if needed. From 1 Sept, standard service visit charges (Rs 300) "
        "apply. Book a slot via our app or call 1800-XXX-XXXX."
    )
    people = (_person("p18-priya", "Priya"),)
    open_obligations = (
        _obligation(
            "o18-machine",
            "Washing machine making a loud grinding noise during spin cycle, reported last week, "
            "not yet booked",
            "home_maintenance",
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt18-1",
            description=(
                "The household already has an unresolved, unbooked washing-machine noise "
                "complaint from last week — this notice's free-service window is only this week "
                "(25-29 Aug), after which the same visit would cost Rs 300; the existing "
                "complaint should be booked into this specific window rather than left open."
            ),
            expected_citation_hint="Free service camp this week only (25-29 Aug)",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-18-appliance-service",
        title="Free service camp — existing complaint should be booked now",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=open_obligations,
            stated_obligations=(),
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 19 — Restaurant reservation: a hard no-child-left-alone constraint
# ---------------------------------------------------------------------------


def _doc_19() -> HeldOutDocument:
    text = "Spice Garden Restaurant\nYour table for 2 is confirmed for tonight, 8:00 PM. See you soon!"
    people = (
        _person("p19-priya", "Priya"),
        _person("p19-rohan", "Rohan"),
        _person("p19-aarav", "Aarav", role=PersonRole.CHILD),
    )
    constraints = (
        _constraint(
            "c19-no-alone",
            ConstraintKind.CUSTODY,
            ConstraintSeverity.HARD,
            "Aarav is 8 and must always have a responsible adult present when at home; never left alone.",
            structured={"min_age_to_leave_alone": "16"},
        ),
    )
    ground_truth = (
        GroundTruthObligation(
            ground_truth_id="gt19-1",
            description=(
                "The reservation is for 2, meaning both Priya and Rohan are going out tonight at "
                "8 PM — and the household has a hard rule that Aarav (age 8) is never left home "
                "alone; supervision needs to be arranged for tonight, which this confirmation "
                "says nothing about."
            ),
            expected_citation_hint="table for 2 is confirmed for tonight, 8:00 PM",
            certainty="clear",
        ),
    )
    return HeldOutDocument(
        doc_id="eval-19-dinner-reservation",
        title="Restaurant reservation confirmation — child-supervision gap",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=constraints,
            open_obligations=(),
            stated_obligations=(),
        ),
        ground_truth_implied=ground_truth,
    )


# ---------------------------------------------------------------------------
# 20 — Library book reminder: hallucination-rate CONTROL / adversarial trap
# ---------------------------------------------------------------------------


def _doc_20() -> HeldOutDocument:
    text = (
        "Greenwood School Library\n\n"
        "Reminder: 2 books borrowed by Aarav Sharma (Class 4B) are due for "
        "return by this Friday. Late fee is Rs 5/day per book after the due "
        "date.\n\n- Librarian"
    )
    people = (_person("p20-aarav", "Aarav", role=PersonRole.CHILD),)
    stated = (
        _obligation(
            "s20-return",
            "Return 2 library books by Friday",
            "errand",
            due_at=datetime(2026, 8, 28, tzinfo=UTC),
        ),
    )
    return HeldOutDocument(
        doc_id="eval-20-library-books",
        title="Library book return reminder — hallucination-rate control / adversarial trap",
        document_text=text,
        household_context=HouseholdContext(
            people=people,
            constraints=(),
            open_obligations=(),
            stated_obligations=stated,
        ),
        ground_truth_implied=(),
        notes=(
            "Adversarial control: genuinely nothing beyond the stated return-by-Friday obligation "
            "follows from this text. A careful human derives no further obligation (no bag to "
            "buy, no card to renew, no reading-log update) — the concrete, plausible-sounding "
            "late-fee figure is exactly the kind of detail that tempts a model into manufacturing "
            "a 'set aside money in case of a late fee' or 'add a reminder' obligation that is not "
            "a genuine implication, just dressed-up restatement or invention."
        ),
    )


EVAL_DOCUMENTS: tuple[HeldOutDocument, ...] = (
    _doc_01(),
    _doc_02(),
    _doc_03(),
    _doc_04(),
    _doc_05(),
    _doc_06(),
    _doc_07(),
    _doc_08(),
    _doc_09(),
    _doc_10(),
    _doc_11(),
    _doc_12(),
    _doc_13(),
    _doc_14(),
    _doc_15(),
    _doc_16(),
    _doc_17(),
    _doc_18(),
    _doc_19(),
    _doc_20(),
)
"""The full held-out set — exactly twenty documents (PHASES.md Phase 4:
"Twenty held-out messy documents never used for tuning")."""


__all__ = ["EVAL_DOCUMENTS", "GroundTruthObligation", "HeldOutDocument"]

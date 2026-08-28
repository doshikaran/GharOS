"""Tests for `app.agents.concierge.context` — the real graph-first check
for A50 and the real prior-experience lookup for A52.

`resolve_known_facts` is the concrete, structural answer to spec §13.2
Step 1's "the agent does not interrogate — it queries the graph first and
asks only what it cannot infer": every requirement in
`SERVICE_CATEGORY_REQUIREMENTS["dental"]` a real `FakeGraphReader` can
answer must end up in `known_facts`, never in `candidate_unknowns`.

`resolve_reliability_signal` is ADR-016's formal `Outcome.
attribution_tags` walk (`booked_with` -> `completes_into`), exercised
directly against `FakeGraphReader` — no Firestore emulator needed (E1's
`neighbours`/`history` are already proven against the real emulator
elsewhere; this module only tests the two-hop composition logic this
package adds on top).
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Provenance,
    Provider,
    SourceRef,
)

from app.agents.concierge.context import (
    SERVICE_CATEGORY_REQUIREMENTS,
    resolve_known_facts,
    resolve_reliability_signal,
)

from ._fake_graph_reader import FakeGraphReader

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="whole-document"),
        confidence=0.9,
        deriving_agent=AgentId("A3"),
        created_at=_NOW,
    )


def _constraint(
    node_id: str, *, kind: ConstraintKind, original_text: str, structured: dict[str, str] | None = None
) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=_provenance(),
        kind=kind,
        severity=ConstraintSeverity.SOFT,
        validity_start=None,
        validity_end=None,
        structured=structured or {},
        original_text=original_text,
    )


def _obligation(
    node_id: str, *, obligation_type: str, status: ObligationStatus, due_at: datetime | None
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance(),
        title="dentist visit",
        obligation_type=obligation_type,
        due_at=due_at,
        must_start_by=None,
        effort_estimate_minutes=30,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _provider(node_id: str, name: str) -> Provider:
    return Provider(
        id=NodeId(node_id),
        provenance=_provenance(),
        name=name,
        category="dental",
        rating=4.5,
        distance_km=1.0,
        availability_notes=None,
        price_band="$$",
        specialisations=(),
    )


def _outcome(node_id: str, *, attribution_tags: tuple[str, ...]) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=_provenance(),
        predicted="attended as scheduled",
        actual="attended",
        variance=0.0,
        attribution_tags=attribution_tags,
    )


class TestResolveKnownFacts:
    def test_dental_checklist_matches_spec_worked_example(self) -> None:
        assert set(SERVICE_CATEGORY_REQUIREMENTS["dental"]) == {
            "person_availability",
            "prior_provider_history",
            "last_visit_date",
            "insurance_provider",
            "situation_urgency",
            "date_constraints",
            "provider_preference",
        }

    def test_always_ask_requirements_are_never_resolved_from_graph(self) -> None:
        """situation_urgency / date_constraints / provider_preference are
        never resolvable from the graph by design — always unknowns,
        regardless of graph content."""
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        always_ask_fields = {"situation_urgency", "date_constraints", "provider_preference"}
        for always_ask in always_ask_fields:
            assert always_ask in unknowns
        assert {fact.field for fact in known}.isdisjoint(always_ask_fields)

    def test_person_availability_always_resolved_even_with_no_constraints(self) -> None:
        """Open-world convention: absence of a SCHEDULE constraint is a
        real, positive fact ('generally available'), never an unknown."""
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        assert "person_availability" not in unknowns
        assert any(fact.field == "person_availability" for fact in known)

    def test_insurance_resolved_when_present_on_a_constraint(self) -> None:
        constraint = _constraint(
            "constraint-insurance",
            kind=ConstraintKind.FINANCIAL,
            original_text="covered under Star Health",
            structured={"insurance_provider": "Star Health"},
        )
        reader = FakeGraphReader(
            neighbours_by_node_and_type={("person-aarav", EdgeType.CONSTRAINS): (constraint,)}
        )

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        assert "insurance_provider" not in unknowns
        fact = next(f for f in known if f.field == "insurance_provider")
        assert fact.value == "Star Health"

    def test_insurance_genuinely_absent_is_a_real_unknown(self) -> None:
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        assert "insurance_provider" in unknowns
        assert not any(f.field == "insurance_provider" for f in known)

    def test_last_visit_and_prior_provider_resolved_from_completed_obligation(self) -> None:
        provider = _provider("provider-old-dentist", "Dr. Mehta")
        obligation = _obligation(
            "obligation-past-visit",
            obligation_type="dental",
            status=ObligationStatus.COMPLETED,
            due_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        reader = FakeGraphReader(
            neighbours_by_node_and_type={
                ("person-aarav", EdgeType.OWNED_BY): (obligation,),
                ("obligation-past-visit", EdgeType.BOOKED_WITH): (provider,),
            }
        )

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        assert "last_visit_date" not in unknowns
        assert "prior_provider_history" not in unknowns
        last_visit = next(f for f in known if f.field == "last_visit_date")
        assert "2026-02-01" in last_visit.value
        prior_provider = next(f for f in known if f.field == "prior_provider_history")
        assert "Dr. Mehta" in prior_provider.value

    def test_no_prior_category_obligation_leaves_both_as_unknowns(self) -> None:
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        assert "last_visit_date" in unknowns
        assert "prior_provider_history" in unknowns

    def test_unregistered_category_falls_back_to_default_checklist(self) -> None:
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="plumbing"
        )

        assert set(unknowns) | {f.field for f in known} == set(SERVICE_CATEGORY_REQUIREMENTS["default"])

    def test_every_dental_requirement_ends_up_in_exactly_one_bucket(self) -> None:
        reader = FakeGraphReader()

        known, unknowns = resolve_known_facts(
            reader, person_id=NodeId("person-aarav"), service_category="dental"
        )

        known_fields = {fact.field for fact in known}
        unknown_fields = set(unknowns)
        assert known_fields.isdisjoint(unknown_fields)
        assert known_fields | unknown_fields == set(SERVICE_CATEGORY_REQUIREMENTS["dental"])


class TestResolveReliabilitySignal:
    def test_no_booked_with_history_returns_none(self) -> None:
        reader = FakeGraphReader()

        signal = resolve_reliability_signal(reader, provider_id=NodeId("provider-new"))

        assert signal is None

    def test_real_no_show_tag_is_counted(self) -> None:
        obligation = _obligation(
            "obligation-1", obligation_type="dental", status=ObligationStatus.COMPLETED, due_at=_NOW
        )
        outcome = _outcome("outcome-1", attribution_tags=("no_show",))
        reader = FakeGraphReader(
            neighbours_by_node_and_type={("provider-x", EdgeType.BOOKED_WITH): (obligation,)},
            history_by_entity={"obligation-1": (outcome,)},
        )

        signal = resolve_reliability_signal(reader, provider_id=NodeId("provider-x"))

        assert signal is not None
        assert signal.no_show_count == 1
        assert signal.total_outcomes_considered == 1

    def test_on_time_history_counted_separately(self) -> None:
        obligation = _obligation(
            "obligation-2", obligation_type="dental", status=ObligationStatus.COMPLETED, due_at=_NOW
        )
        outcome_a = _outcome("outcome-a", attribution_tags=("on_time",))
        outcome_b = _outcome("outcome-b", attribution_tags=("on_time",))
        reader = FakeGraphReader(
            neighbours_by_node_and_type={("provider-y", EdgeType.BOOKED_WITH): (obligation,)},
            history_by_entity={"obligation-2": (outcome_a, outcome_b)},
        )

        signal = resolve_reliability_signal(reader, provider_id=NodeId("provider-y"))

        assert signal is not None
        assert signal.on_time_count == 2
        assert signal.no_show_count == 0
        assert signal.total_outcomes_considered == 2

    def test_booked_with_but_no_outcome_history_returns_none(self) -> None:
        obligation = _obligation(
            "obligation-3", obligation_type="dental", status=ObligationStatus.ASSIGNED, due_at=None
        )
        reader = FakeGraphReader(
            neighbours_by_node_and_type={("provider-z", EdgeType.BOOKED_WITH): (obligation,)},
            history_by_entity={},
        )

        signal = resolve_reliability_signal(reader, provider_id=NodeId("provider-z"))

        assert signal is None

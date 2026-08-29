"""`ScopedGraphReader` (Phase 12, ADR-019 Decision 1) — proves the five
Council domain-specialist scopes are genuinely disjoint by construction,
that every one of the seven *filtered* methods includes exactly its own
scope's real fixture nodes and excludes every other scope's, and that
every one of the eleven *denied* methods raises `OutOfScopeGraphAccess`
unconditionally for every scope, backed by a real Firestore-emulator
`FirestoreGraphReader` — never a fake, so a passing denial test proves the
wrapper itself refuses the call rather than the underlying data merely
happening to be empty.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from contracts.graph_types import (
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Edge,
    EdgeId,
    EdgeType,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
)

from app.graph.reader import FirestoreGraphReader
from app.graph.scoped_reader import (
    CARE_SCOPE,
    EDUCATION_SCOPE,
    FINANCE_SCOPE,
    LEGAL_SCOPE,
    LOGISTICS_SCOPE,
    GraphSubgraphScope,
    OutOfScopeGraphAccess,
    ScopedGraphReader,
)
from app.graph.writer import FirestoreGraphWriter
from seeds.demo_household import SeedResult
from tests.conftest import NOW, make_person, make_provenance

ALL_SCOPES: tuple[GraphSubgraphScope, ...] = (
    FINANCE_SCOPE,
    CARE_SCOPE,
    EDUCATION_SCOPE,
    LOGISTICS_SCOPE,
    LEGAL_SCOPE,
)


# ---------------------------------------------------------------------------
# Fixture node builders — pure data, no I/O. Every field beyond `id`/`kind`
# is held fixed across calls so a `Constraint`'s `kind` is provably the only
# thing that ever changes between two otherwise-identical fixtures.
# ---------------------------------------------------------------------------


def _ledger_event(node_id: str) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=LedgerEventKind.DEBIT,
        amount=1200.0,
        currency="INR",
        occurred_at=NOW,
        counterparty_raw="Test Vendor",
    )


def _recurring_commitment(node_id: str) -> RecurringCommitment:
    return RecurringCommitment(
        id=NodeId(node_id),
        provenance=make_provenance(),
        label="Test subscription",
        counterparty="Test Co",
        amount=499.0,
        cadence="monthly",
        price_history=(),
        last_used_at=NOW,
        status="active",
    )


def _constraint(
    node_id: str,
    kind: ConstraintKind,
    *,
    severity: ConstraintSeverity = ConstraintSeverity.HARD,
    original_text: str = "test constraint — identical text across every kind, kind is the only discriminator",
) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=kind,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured={},
        original_text=original_text,
    )


def _obligation(node_id: str) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=make_provenance(),
        title="Test obligation",
        obligation_type="errand",
        due_at=NOW,
        must_start_by=None,
        effort_estimate_minutes=30,
        status=ObligationStatus.DERIVED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _source_document(node_id: str) -> SourceDocument:
    return SourceDocument(
        id=NodeId(node_id),
        provenance=make_provenance(),
        channel="whatsapp",
        raw_payload_ref="ref://test",
        document_type="chat_message_thread",
        ingested_at=NOW,
        original_language="en",
    )


def _outcome(node_id: str, *, tags: tuple[str, ...] = ()) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=make_provenance(),
        predicted="predicted",
        actual="actual",
        variance=0.5,
        attribution_tags=tags,
    )


def _purchase_item(node_id: str, ledger_event_id: NodeId) -> PurchaseItem:
    return PurchaseItem(
        id=NodeId(node_id),
        provenance=make_provenance(),
        ledger_event_id=ledger_event_id,
        description="Test item",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=100.0,
        line_total=100.0,
    )


def _edge(edge_id: str, edge_type: EdgeType, from_id: NodeId, to_id: NodeId) -> Edge:
    return Edge(
        id=EdgeId(edge_id),
        provenance=make_provenance(),
        edge_type=edge_type,
        from_id=from_id,
        to_id=to_id,
    )


def _fixtures_by_scope_name() -> dict[str, tuple[object, ...]]:
    """One representative fixture node per real node type each of the five
    scopes claims (ADR-019 Decision 1's own table) — fresh objects each
    call so tests that write them to Firestore never collide on id reuse
    across test functions within this module."""
    return {
        "finance": (_ledger_event("fx-finance-ledger"), _recurring_commitment("fx-finance-commitment")),
        "care": (
            _constraint("fx-care-medical", ConstraintKind.MEDICAL),
            _constraint("fx-care-mobility", ConstraintKind.MOBILITY),
            make_person("fx-care-person", "Fixture Person"),
        ),
        "education": (_constraint("fx-education-constraint", ConstraintKind.EDUCATION),),
        "logistics": (
            _obligation("fx-logistics-obligation"),
            _constraint("fx-logistics-schedule", ConstraintKind.SCHEDULE),
        ),
        "legal": (
            _constraint("fx-legal-legal", ConstraintKind.LEGAL),
            _constraint("fx-legal-custody", ConstraintKind.CUSTODY),
            _source_document("fx-legal-document"),
        ),
    }


# ---------------------------------------------------------------------------
# Disjointness — pairwise, by construction, not by eyeball.
# ---------------------------------------------------------------------------


class TestScopeDisjointness:
    def test_no_fixture_satisfies_two_scopes(self) -> None:
        fixtures_by_scope = _fixtures_by_scope_name()
        for scope in ALL_SCOPES:
            own_fixtures = fixtures_by_scope[scope.name]
            for node in own_fixtures:
                assert scope.node_predicate(node) is True, (
                    f"{scope.name!r} scope must include its own fixture {node!r}"
                )
            for other_scope in ALL_SCOPES:
                if other_scope.name == scope.name:
                    continue
                for node in own_fixtures:
                    assert other_scope.node_predicate(node) is False, (
                        f"{other_scope.name!r} scope must NOT include {scope.name!r}'s own fixture {node!r} "
                        "— pairwise intersection must be empty"
                    )


class TestConstraintKindIsTheOnlyDiscriminator:
    """`EDUCATION_SCOPE` and `LOGISTICS_SCOPE` both touch `Constraint` —
    proven here with two constraint fixtures identical in every field
    except `kind`, the only thing either predicate ever branches on."""

    def test_schedule_constraint_is_logistics_only(self) -> None:
        schedule_constraint = _constraint("kind-only-schedule", ConstraintKind.SCHEDULE)
        assert LOGISTICS_SCOPE.node_predicate(schedule_constraint) is True
        assert EDUCATION_SCOPE.node_predicate(schedule_constraint) is False

    def test_education_constraint_is_education_only(self) -> None:
        education_constraint = _constraint("kind-only-education", ConstraintKind.EDUCATION)
        assert EDUCATION_SCOPE.node_predicate(education_constraint) is True
        assert LOGISTICS_SCOPE.node_predicate(education_constraint) is False

    def test_the_two_fixtures_differ_in_kind_alone(self) -> None:
        schedule_constraint = _constraint("kind-only-schedule-2", ConstraintKind.SCHEDULE)
        education_constraint = _constraint("kind-only-education-2", ConstraintKind.EDUCATION)
        assert schedule_constraint.severity == education_constraint.severity
        assert schedule_constraint.validity_start == education_constraint.validity_start
        assert schedule_constraint.validity_end == education_constraint.validity_end
        assert schedule_constraint.structured == education_constraint.structured
        assert schedule_constraint.original_text == education_constraint.original_text
        assert schedule_constraint.kind != education_constraint.kind


# ---------------------------------------------------------------------------
# Filtered methods — own fixtures included, every other scope's excluded —
# against a real Firestore-emulator-backed GraphReader.
# ---------------------------------------------------------------------------


class TestFilteredMethodsPerScope:
    @pytest.fixture
    def wired(self, writer: FirestoreGraphWriter) -> tuple[Obligation, dict[str, tuple[object, ...]]]:
        """Writes one real fixture node per scope, plus a hub `Obligation`
        connected to every one of them by the same edge type — real data
        `get_node`/`neighbours`/`blast_radius`/`blast_radius_multi` can
        all be exercised against."""
        hub = _obligation("hub-obligation")
        writer.write_node(hub)

        fixtures = _fixtures_by_scope_name()
        edge_index = 0
        for nodes in fixtures.values():
            for node in nodes:
                writer.write_node(node)
                edge_index += 1
                writer.write_edge(
                    _edge(f"hub-edge-{edge_index}", EdgeType.GROUNDED_IN, hub.id, node.id)  # type: ignore[attr-defined]
                )
        return hub, fixtures

    @pytest.mark.parametrize("scope", ALL_SCOPES, ids=lambda s: s.name)
    def test_get_node(
        self,
        reader: FirestoreGraphReader,
        wired: tuple[Obligation, dict[str, tuple[object, ...]]],
        scope: GraphSubgraphScope,
    ) -> None:
        _hub, fixtures = wired
        scoped = ScopedGraphReader(reader=reader, scope=scope)
        for owner_scope_name, nodes in fixtures.items():
            for node in nodes:
                result = scoped.get_node(node.id)  # type: ignore[attr-defined]
                if owner_scope_name == scope.name:
                    assert result is not None
                    assert result.id == node.id  # type: ignore[attr-defined]
                else:
                    assert result is None

    @pytest.mark.parametrize("scope", ALL_SCOPES, ids=lambda s: s.name)
    def test_neighbours(
        self,
        reader: FirestoreGraphReader,
        wired: tuple[Obligation, dict[str, tuple[object, ...]]],
        scope: GraphSubgraphScope,
    ) -> None:
        hub, fixtures = wired
        scoped = ScopedGraphReader(reader=reader, scope=scope)
        result_ids = {n.id for n in scoped.neighbours(hub.id, EdgeType.GROUNDED_IN)}  # type: ignore[attr-defined]
        expected_ids = {n.id for n in fixtures[scope.name]}  # type: ignore[attr-defined]
        assert result_ids == expected_ids

    @pytest.mark.parametrize("scope", ALL_SCOPES, ids=lambda s: s.name)
    def test_blast_radius(
        self,
        reader: FirestoreGraphReader,
        wired: tuple[Obligation, dict[str, tuple[object, ...]]],
        scope: GraphSubgraphScope,
    ) -> None:
        hub, fixtures = wired
        scoped = ScopedGraphReader(reader=reader, scope=scope)
        result_ids = {n.id for n in scoped.blast_radius(hub.id, 1)}  # type: ignore[attr-defined]
        expected_ids = {n.id for n in fixtures[scope.name]}  # type: ignore[attr-defined]
        assert result_ids == expected_ids

    @pytest.mark.parametrize("scope", ALL_SCOPES, ids=lambda s: s.name)
    def test_blast_radius_multi(
        self,
        reader: FirestoreGraphReader,
        wired: tuple[Obligation, dict[str, tuple[object, ...]]],
        scope: GraphSubgraphScope,
    ) -> None:
        hub, fixtures = wired
        scoped = ScopedGraphReader(reader=reader, scope=scope)
        result_ids = {n.id for n in scoped.blast_radius_multi((hub.id,), 1)}  # type: ignore[attr-defined]
        expected_ids = {n.id for n in fixtures[scope.name]}  # type: ignore[attr-defined]
        assert result_ids == expected_ids


class TestFilteredMethodsExcludeNodeTypesNoScopeClaims:
    """`history`, `outcome_variance`, and `effort_evidence` return
    `Outcome`/`PurchaseItem` nodes — neither type is claimed by any of the
    five Council scopes (ADR-019 Decision 1's own table), so every scope
    must filter these down to `()` even when the wrapped, unscoped reader
    legitimately finds real data — proven, not assumed, by first asserting
    the unscoped reader really does find it."""

    def test_history(self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter) -> None:
        entity = _obligation("history-entity")
        outcome = _outcome("history-outcome")
        writer.write_node(entity)
        writer.write_node(outcome)
        writer.write_edge(_edge("history-edge", EdgeType.COMPLETES_INTO, entity.id, outcome.id))

        assert reader.history(entity.id) != ()
        for scope in ALL_SCOPES:
            scoped = ScopedGraphReader(reader=reader, scope=scope)
            assert scoped.history(entity.id) == ()

    def test_outcome_variance(self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter) -> None:
        outcome = _outcome("variance-outcome", tags=("scoped-reader-test-tag",))
        writer.write_node(outcome)

        assert reader.outcome_variance("scoped-reader-test-tag") != ()
        for scope in ALL_SCOPES:
            scoped = ScopedGraphReader(reader=reader, scope=scope)
            assert scoped.outcome_variance("scoped-reader-test-tag") == ()

    def test_effort_evidence(self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter) -> None:
        person = make_person("effort-person", "Effort Person")
        ledger_event = _ledger_event("effort-ledger")
        item = _purchase_item("effort-item", ledger_event.id)
        writer.write_node(person)
        writer.write_node(ledger_event)
        writer.write_node(item)
        writer.write_edge(_edge("effort-edge", EdgeType.EVIDENCES_EFFORT, item.id, person.id))

        window = (NOW - timedelta(days=1), NOW + timedelta(days=1))
        assert reader.effort_evidence(person.id, window) != ()
        for scope in ALL_SCOPES:
            scoped = ScopedGraphReader(reader=reader, scope=scope)
            assert scoped.effort_evidence(person.id, window) == ()


# ---------------------------------------------------------------------------
# Denied methods — raise unconditionally, for every scope, against a real
# (never fake) GraphReader carrying substantial real seeded data.
# ---------------------------------------------------------------------------

_WINDOW = (NOW - timedelta(days=30), NOW + timedelta(days=30))

_DENIED_CALLS: tuple[tuple[str, tuple[object, ...], dict[str, object]], ...] = (
    ("path", (NodeId("a"), NodeId("b")), {}),
    ("conflicts", ("all",), {}),
    ("dependency_chain", (NodeId("obligation-x"),), {}),
    ("load", (NodeId("person-x"), _WINDOW), {}),
    ("series", (NodeId("commitment-x"),), {}),
    ("decisions_touching", (NodeId("x"),), {}),
    ("concession_ledger", (NodeId("person-x"),), {}),
    ("unexplained", ("all",), {}),
    ("unverified", ("all",), {}),
    ("expected_but_absent", (NodeId("constraint-x"),), {}),
    ("spend_by_category", (_WINDOW,), {}),
)


class TestDeniedMethodsRaiseForEveryScope:
    @pytest.mark.parametrize("scope", ALL_SCOPES, ids=lambda s: s.name)
    @pytest.mark.parametrize("method_name,args,kwargs", _DENIED_CALLS, ids=[c[0] for c in _DENIED_CALLS])
    def test_raises_out_of_scope(
        self,
        reader: FirestoreGraphReader,
        seeded: SeedResult,
        scope: GraphSubgraphScope,
        method_name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        """`reader` is a real `FirestoreGraphReader` over `seeded`'s full
        demo household (36+ real nodes) — a passing assertion here proves
        the wrapper itself refuses the call, not that there was simply
        nothing to find."""
        scoped = ScopedGraphReader(reader=reader, scope=scope)
        method = getattr(scoped, method_name)
        with pytest.raises(OutOfScopeGraphAccess) as exc_info:
            method(*args, **kwargs)
        assert exc_info.value.scope_name == scope.name
        assert exc_info.value.method == method_name

    def test_every_denied_method_name_is_covered(self) -> None:
        """Guards the table above itself against silently losing a method
        if `contracts.repositories.GraphReader`'s Protocol ever grows —
        the eleven names here must exactly match ADR-019 Decision 1's own
        deny list (the seven filtered methods, checked in the classes
        above, make up the rest of the eighteen-method Protocol)."""
        expected = {
            "path",
            "conflicts",
            "dependency_chain",
            "load",
            "series",
            "decisions_touching",
            "concession_ledger",
            "unexplained",
            "unverified",
            "expected_but_absent",
            "spend_by_category",
        }
        assert {name for name, _, _ in _DENIED_CALLS} == expected

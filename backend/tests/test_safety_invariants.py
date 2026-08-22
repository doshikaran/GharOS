"""The eight safety invariants (gharos-standards skill) — one test (or
`@pytest.mark.skip` placeholder naming the phase it lands in) per
invariant, growing every phase. Never skipped once its introduction phase
lands, never `xfail`.

| # | Invariant                              | Enforced by                | Status here                  |
|---|-----------------------------------------|-----------------------------|-------------------------------|
| 3 | Provenance on every node/edge           | Repository write guard      | REAL (Firestore, Phase 1)     |
| 2 | Audit before execute                    | write_before_execute        | REAL (Firestore, Phase 1)     |
| 4 | Low confidence escalates                | Confidence Arbiter          | skip -> Phase 4               |
| 1 | Money reasoners hold no money tools     | Tool registration           | skip -> Phase 5               |
| 5 | Financial/irreversible need approval    | Approval Gate               | skip -> Phase 5               |
| 7 | No fabricated tool success               | Tool error contract         | skip -> Phase 5               |
| 6 | No debate framing                       | Code review + lint rule     | skip -> Phase 12              |
| 8 | Voice confers no action capability      | Voice intent routing        | skip -> Phase 13              |

Invariants #2 and #3 were provable against Phase 0's in-memory stub
repositories; this phase (E1, Phase 1) upgrades both proofs to run against
the real, Firestore-emulator-backed `FirestoreGraphWriter` and
`FirestoreAuditLog` / `write_before_execute`, per the E1 charter's
explicit instruction to upgrade — not merely re-point — these two test
classes. The rest of this file (everything from "Invariants introduced in
later phases" onward) is untouched from Phase 0: those invariants are not
E1's to implement, and their skip placeholders name the correct future
phase already.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from contracts.actions import ActionResult, AuditRef, IdempotencyKey, RiskTier
from contracts.errors import ProvenanceMissing
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.audit.audit_log import FirestoreAuditLog
from app.audit.errors import AuditNotWritten
from app.audit.write_before_execute import AuditGuardedAction, write_before_execute
from app.graph.writer import FirestoreGraphWriter
from app.persistence.provenance_guard import validate_provenance

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _valid_provenance() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
        confidence=0.9,
        deriving_agent=AgentId("A0"),
        created_at=datetime.now(UTC),
    )


def _valid_person(node_id: str = "person-1") -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=_valid_provenance(),
        display_name="Priya",
        aliases=("Priya Sharma",),
        role=PersonRole.ADULT,
        can_drive=True,
        can_sign=True,
        has_bank_access=True,
        has_medical_proxy=False,
        contact_channels=("whatsapp:+91-...",),
        language_profile=LanguageProfile(
            primary_language="hi",
            languages_understood=("hi", "en"),
            script_preference="devanagari",
            code_mixing_profile="hi-en",
            formality_preference="informal",
            literacy_mode=LiteracyMode.BOTH,
        ),
    )


# ---------------------------------------------------------------------------
# Invariant #3 — provenance on every node/edge (Phase 1, real Firestore)
# ---------------------------------------------------------------------------


class TestInvariant3ProvenanceEnforcement:
    """A repository write missing any required provenance field must be
    REJECTED — not logged, not warned about, rejected (E1 charter,
    "Provenance enforcement"). Proven with a hypothesis fuzz test per the
    gharos-standards skill: "a handful of example-based tests is not
    sufficient evidence for 'structurally impossible'." Run against the
    real, Firestore-emulator-backed `FirestoreGraphWriter` — see
    `test_provenance_guard.py` for the full fuzz-test suite this class
    summarizes the headline proof of.
    """

    def test_write_node_accepts_complete_provenance(self, writer: FirestoreGraphWriter) -> None:
        node_id = writer.write_node(_valid_person())
        assert node_id == NodeId("person-1")

    def test_write_node_rejects_none_provenance(self, writer: FirestoreGraphWriter) -> None:
        node = SimpleNamespace(id=NodeId("bad-1"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.write_node(node)

    def test_write_node_rejects_missing_provenance_attribute(self, writer: FirestoreGraphWriter) -> None:
        node = SimpleNamespace(id=NodeId("bad-2"))  # no `provenance` at all
        with pytest.raises(ProvenanceMissing):
            writer.write_node(node)

    @given(
        missing_fields=st.lists(
            st.sampled_from(["derivation", "source_ref", "confidence", "deriving_agent", "created_at"]),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=50)
    def test_write_node_rejects_every_combination_of_missing_fields(
        self, writer: FirestoreGraphWriter, missing_fields: list[str]
    ) -> None:
        """Fuzzes every non-empty subset of the five provenance fields
        being absent and asserts the REAL Firestore-backed guard rejects
        every single one — this is the "structurally impossible to
        bypass" proof Gate 1 requires, not a handful of hand-picked
        examples."""
        valid = _valid_provenance()
        provenance_fields = {
            "derivation": valid.derivation,
            "source_ref": valid.source_ref,
            "confidence": valid.confidence,
            "deriving_agent": valid.deriving_agent,
            "created_at": valid.created_at,
            "superseded_at": valid.superseded_at,
        }
        fake_provenance = SimpleNamespace(**provenance_fields)
        for field_name in missing_fields:
            delattr(fake_provenance, field_name)

        node = SimpleNamespace(id=NodeId("fuzzed"), provenance=fake_provenance)
        with pytest.raises(ProvenanceMissing) as exc_info:
            writer.write_node(node)
        # every field we actually removed must show up as reported-missing
        # (source_ref is the one conditional case: dropping it is only
        # reported when derivation isn't AMBIGUOUS, which is what
        # _valid_provenance() uses here).
        for field_name in missing_fields:
            assert field_name in exc_info.value.missing_fields

    def test_ambiguous_derivation_permits_none_source_ref(self) -> None:
        """source_ref is the one field that is legitimately None for
        AMBIGUOUS-with-no-single-source provenance (spec §5.6) — the guard
        must not reject this as "missing"."""
        provenance = Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.4,
            deriving_agent=AgentId("A10"),
            created_at=datetime.now(UTC),
        )
        validate_provenance(SimpleNamespace(id=NodeId("ambiguous-1"), provenance=provenance))

    def test_supersede_rejects_incomplete_new_node_and_leaves_old_untouched(
        self, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(_valid_person())

        bad_new_version = SimpleNamespace(id=NodeId("person-1"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.supersede_node(NodeId("person-1"), bad_new_version)

        # rejected supersession must not have mutated the original
        current = writer._store.get_node(NodeId("person-1"))  # noqa: SLF001
        assert current is not None
        assert current.provenance.superseded_at is None


# ---------------------------------------------------------------------------
# Invariant #2 — audit before execute (Phase 1, real Firestore)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _FakeApprovedRequestAction(AuditGuardedAction[str]):
    """A minimal concrete `Action` built on the real `AuditGuardedAction`
    base class (`backend/app/audit/write_before_execute.py`) — this is
    what makes "audit before execute" structural rather than a
    documentation promise, upgraded from Phase 0's hand-rolled test double
    that merely demonstrated the *pattern*."""

    risk_tier: RiskTier
    idempotency_key: IdempotencyKey
    audit_ref: AuditRef | None

    def _perform(self) -> ActionResult[str]:
        return ActionResult.success("done")


class TestInvariant2AuditBeforeExecute:
    """An Action cannot reach `execute()` with a `None` `audit_ref` — this
    is structural, not "please remember to call audit first" (E1
    charter). `AuditGuardedAction.execute()` (Phase 1,
    `backend/app/audit/write_before_execute.py`) enforces this for any
    concrete Action built on it; `write_before_execute` is the sanctioned
    way to obtain a populated, durably-written `AuditRef` in the first
    place. Proven here against the real, Firestore-emulator-backed
    `FirestoreAuditLog` — see `test_audit_and_write_before_execute.py`
    for the full proof suite.
    """

    def test_execute_without_audit_ref_is_refused(self) -> None:
        action = _FakeApprovedRequestAction(
            risk_tier=RiskTier.R1_NOTIFY,
            idempotency_key=IdempotencyKey(entity_id="e1", action_type="notify", cycle="2026-08"),
            audit_ref=None,
        )
        with pytest.raises(AuditNotWritten):
            action.execute()

    def test_audit_written_before_execute_succeeds(self, audit_log: FirestoreAuditLog) -> None:
        def build_action(audit_ref: AuditRef) -> _FakeApprovedRequestAction:
            return _FakeApprovedRequestAction(
                risk_tier=RiskTier.R1_NOTIFY,
                idempotency_key=IdempotencyKey(entity_id="e1", action_type="notify", cycle="2026-08"),
                audit_ref=audit_ref,
            )

        result = write_before_execute(
            audit_log,
            action_type="notify",
            payload={"summary": "test action"},
            occurred_at=datetime.now(UTC),
            build_action=build_action,
        )
        assert result.ok is True
        assert result.value == "done"


# ---------------------------------------------------------------------------
# Invariants introduced in later phases — tracked placeholders, not silently
# absent (gharos-standards skill: "the file itself, and every placeholder,
# must exist from Phase 1 onward and must be visibly tracked").
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implemented in Phase 5")
def test_invariant_1_money_reasoners_hold_no_money_tools() -> None:
    """No agent that reasons about money may also move money — enforced by
    tool registration (Phase 5)."""


@pytest.mark.skip(reason="implemented in Phase 4")
def test_invariant_4_low_confidence_escalates() -> None:
    """Low-confidence outputs escalate; they never silently act — enforced
    by the Confidence Arbiter (Phase 4)."""


@pytest.mark.skip(reason="implemented in Phase 5")
def test_invariant_5_financial_irreversible_needs_approval() -> None:
    """Financial and irreversible actions require explicit human approval —
    enforced by the Approval Gate (Phase 5)."""


@pytest.mark.skip(reason="implemented in Phase 12")
def test_invariant_6_no_debate_framing() -> None:
    """Agent-to-agent interaction is never framed as "debate" — it is
    specialization and interest representation — enforced by code review
    and a lint rule (Phase 12)."""


@pytest.mark.skip(reason="implemented in Phase 5")
def test_invariant_7_no_fabricated_tool_success() -> None:
    """A failed tool call never produces a fabricated success — enforced by
    the tool error contract (Phase 5)."""


@pytest.mark.skip(reason="implemented in Phase 13")
def test_invariant_8_voice_confers_no_action_capability() -> None:
    """Voice confers no action capability beyond what was pre-authorised —
    enforced by voice intent routing (Phase 13)."""

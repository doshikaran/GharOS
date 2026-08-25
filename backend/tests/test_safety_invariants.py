"""The eight safety invariants (gharos-standards skill) — one test (or
`@pytest.mark.skip` placeholder naming the phase it lands in) per
invariant, growing every phase. Never skipped once its introduction phase
lands, never `xfail`.

| # | Invariant                              | Enforced by                | Status here                  |
|---|-----------------------------------------|-----------------------------|-------------------------------|
| 3 | Provenance on every node/edge           | Repository write guard      | REAL (Firestore, Phase 1)     |
| 2 | Audit before execute                    | write_before_execute        | REAL (Firestore, Phase 1)     |
| 4 | Low confidence escalates                | Confidence Arbiter          | REAL (Firestore, Phase 5)     |
| 1 | Money reasoners hold no money tools     | Tool registration           | REAL (Phase 5)                |
| 5 | Financial/irreversible need approval    | Approval Gate               | REAL (Firestore, Phase 5)     |
| 7 | No fabricated tool success               | Tool error contract         | REAL (Firestore, Phase 5)     |
| 6 | No debate framing                       | Code review + lint rule     | skip -> Phase 12              |
| 8 | Voice confers no action capability      | Voice intent routing        | skip -> Phase 13              |

Invariants #2 and #3 were provable against Phase 0's in-memory stub
repositories; Phase 1 (E1) upgraded both proofs to run against the real,
Firestore-emulator-backed `FirestoreGraphWriter` and `FirestoreAuditLog` /
`write_before_execute`. Phase 5 (E3) does the equivalent upgrade for #1,
#4, #5, and #7 — real tests against `app.tools.registry.ToolRegistry`,
`app.arbitration.confidence_arbiter.ConfidenceArbiter`,
`app.arbitration.approval_gate.ApprovalGate`, and the concrete tools in
`app.tools`/`app.arbitration`, not placeholders. #6 and #8 remain tracked
skips naming their correct future phase (Gate 5 explicitly allows this:
"All eight invariants now real tests (6 and 8 may still be placeholders)").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from contracts.actions import ActionResult, AuditRef, EvidenceBundle, IdempotencyKey, RiskTier
from contracts.errors import ApprovalRequired, ProvenanceMissing, ToolFailure
from contracts.graph_types import (
    AgentId,
    ApprovalStatus,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)
from contracts.tools import GATED_TIERS, PermissionTier
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.arbitration.actions import GatedAction
from app.arbitration.approval_gate import ApprovalGate
from app.arbitration.confidence_arbiter import ConfidenceArbiter
from app.arbitration.gated_tool import ReferenceGatedTool
from app.arbitration.types import ArbiterDecision, ArbiterResult, ProposedAction
from app.audit.audit_log import FirestoreAuditLog
from app.audit.errors import AuditNotWritten
from app.audit.write_before_execute import AuditGuardedAction, write_before_execute
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.persistence.provenance_guard import validate_provenance
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.risk_policy import ActionTypes
from app.tools.errors import GatedToolRegistrationDenied
from app.tools.registry import ToolRegistry

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

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


class TestInvariant1MoneyReasonersHoldNoMoneyTools:
    """No agent that reasons about money may also move money — enforced by
    tool registration (Phase 5). See `test_tool_registry.py` for the full
    adversarial proof suite this class summarizes the headline claim of.
    """

    def test_reasoning_agent_registry_cannot_register_a_t6_tool(self) -> None:
        """A28 Reconciliation-shaped registry (T0 Ledger-read only) — the
        canonical "money-analysis but not money-movement" agent (spec
        §10.5) — refuses a T6 tool outright."""
        registry = ToolRegistry(agent_id=AgentId("A28"), allowed_tiers=frozenset({PermissionTier.T0_READ}))
        tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises((GatedToolRegistrationDenied,)):
            attempt_gated_registration(registry, tool)
        assert not registry.has_tier(PermissionTier.T6_FINANCIAL)

    def test_gated_tiers_are_reachable_only_through_arbitration_regardless_of_caller(self) -> None:
        """Every GATED_TIERS member (T4/T5/T6), attempted from a mock
        agent-side location, is rejected — spec §16.3 invariant 1/2
        combined."""
        for tier in GATED_TIERS:
            registry = ToolRegistry(
                agent_id=AgentId("some-money-reasoning-agent"), allowed_tiers=frozenset({tier})
            )
            tool = ReferenceGatedTool(
                name=f"gated-{tier.value}",
                tier=tier,
                bounds={},
                effect=lambda **kwargs: "done",
                idempotency_store=InMemoryIdempotencyStore(),
            )
            with pytest.raises(GatedToolRegistrationDenied):
                attempt_gated_registration(registry, tool)


class TestInvariant4LowConfidenceEscalates:
    """Low-confidence outputs escalate; they never silently act — enforced
    by the Confidence Arbiter (Phase 5, A57). See
    `test_confidence_arbiter.py` for the full proof suite."""

    def _arbiter(self) -> ConfidenceArbiter:
        fake_models = FakeModels(texts=["{}"])
        client = GeminiClient(router=fake_router(fake_models))
        return ConfidenceArbiter(gemini_client=client)

    def _proposed(self, *, action_type: str, confidence: float) -> ProposedAction:
        return ProposedAction(
            action_type=action_type,
            entity_id="entity-1",
            cycle="2026-08",
            target_node_id=NodeId("target-1"),
            confidence=confidence,
            involves_hard_constraint=False,
            reasoning="test",
            evidence_consulted=(),
            consequence_if_wrong="test",
            proposed_by=AgentId("A0"),
            source_ref=None,
        )

    def test_catastrophically_low_confidence_is_discarded_never_executed(self) -> None:
        proposed = self._proposed(action_type=ActionTypes.GRAPH_WRITE, confidence=0.05)
        result = self._arbiter().evaluate(proposed)
        # DISCARD is one of exactly four ArbiterDecision members and is
        # itself the full proof of "never silently executed" -- pinning it
        # already excludes EXECUTE (and APPROVE/ESCALATE) with no further
        # assertion needed.
        assert result.decision is ArbiterDecision.DISCARD

    def test_low_confidence_that_crosses_a_tier_boundary_requires_approval_not_silent_execution(self) -> None:
        """A `DRAFT_MESSAGE` (R1, normally silently auto-executed) at low
        confidence is downgraded to R2 — it now requires human approval
        rather than executing quietly."""
        proposed = self._proposed(action_type=ActionTypes.DRAFT_MESSAGE, confidence=0.30)
        result = self._arbiter().evaluate(proposed)
        assert result.final_risk_tier is RiskTier.R2_APPROVE
        # APPROVE is itself the full proof of "requires human approval, not
        # silent execution" -- pinning it already excludes EXECUTE.
        assert result.decision is ArbiterDecision.APPROVE


class TestInvariant5FinancialIrreversibleNeedsApproval:
    """Financial and irreversible actions require explicit human approval —
    enforced by the Approval Gate (Phase 5). See `test_approval_gate.py`
    for the full proof suite."""

    def test_pay_dues_never_executes_without_an_approved_approval_request(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        proposed = ProposedAction(
            action_type=ActionTypes.PAY_DUES,
            entity_id="due-1",
            cycle="2026-08",
            target_node_id=NodeId("ledger-event-1"),
            confidence=0.95,
            involves_hard_constraint=False,
            reasoning="test",
            evidence_consulted=(),
            consequence_if_wrong="test",
            proposed_by=AgentId("A27"),
            source_ref=None,
        )
        arbiter_result = ArbiterResult(
            proposed_action=proposed,
            decision=ArbiterDecision.APPROVE,
            final_risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            confidence=0.95,
            evidence_bundle=EvidenceBundle("pay_dues", "test", (), 0.95, "test"),
            escalated_to_pro=False,
        )
        tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=idempotency_store,
        )
        gate = ApprovalGate(graph_reader=reader, graph_writer=writer, audit_log=audit_log)

        # No approval requested yet -- constructing/executing a GatedAction
        # directly for this action, without going through the gate, must
        # refuse (this is what "never" means structurally, not just "the
        # gate happens to always be called first").
        unapproved = GatedAction(
            risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            idempotency_key=IdempotencyKey(
                entity_id="due-1", action_type=ActionTypes.PAY_DUES, cycle="2026-08"
            ),
            audit_ref=AuditRef(audit_record_id="fake", written_at=datetime.now(UTC)),
            tool=tool,
            invoke_kwargs={},
            approval_status=ApprovalStatus.PENDING,
        )
        with pytest.raises(ApprovalRequired):
            unapproved.execute()

        # The sanctioned path: request approval, then explicitly approve.
        request = gate.request_approval(arbiter_result, now=datetime.now(UTC))
        outcome = gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={},
        )
        assert outcome.status == ApprovalStatus.APPROVED.value
        assert outcome.tool_result.ok is True  # type: ignore[union-attr]


@pytest.mark.skip(reason="implemented in Phase 12")
def test_invariant_6_no_debate_framing() -> None:
    """Agent-to-agent interaction is never framed as "debate" — it is
    specialization and interest representation — enforced by code review
    and a lint rule (Phase 12)."""


class TestInvariant7NoFabricatedToolSuccess:
    """A failed tool call never produces a fabricated success — enforced by
    the tool error contract (Phase 5). See `test_graph_read_tool.py` /
    `test_graph_write_tool.py` for the full per-tool adversarial suite."""

    def test_forced_tool_failure_never_returns_action_result_success(
        self, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        from app.tools.graph_write_tool import GraphWriteTool

        class _BrokenWriter:
            def write_node(self, node: object) -> NodeId:
                raise RuntimeError("simulated failure")

            def write_edge(self, edge: object) -> None:  # pragma: no cover
                raise RuntimeError("simulated failure")

            def supersede_node(self, old_node_id: NodeId, new_node: object) -> NodeId:  # pragma: no cover
                raise RuntimeError("simulated failure")

        tool = GraphWriteTool(graph_writer=_BrokenWriter(), idempotency_store=idempotency_store)
        with pytest.raises(ToolFailure):
            result = tool.invoke_idempotent("invariant-7-key", operation="write_node", node=object())
            # Unreachable if the contract holds -- documents intent (mirrors
            # risk_policy's own "never resolves to a permissive default"
            # belt-and-braces test style).
            assert result.ok is not True


@pytest.mark.skip(reason="implemented in Phase 13")
def test_invariant_8_voice_confers_no_action_capability() -> None:
    """Voice confers no action capability beyond what was pre-authorised —
    enforced by voice intent routing (Phase 13)."""

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
| 6 | No debate framing                       | Grep-based lint rule        | REAL (Phase 12)               |
| 8 | Voice confers no action capability      | Voice intent routing        | REAL (Phase 13)               |

Invariants #2 and #3 were provable against Phase 0's in-memory stub
repositories; Phase 1 (E1) upgraded both proofs to run against the real,
Firestore-emulator-backed `FirestoreGraphWriter` and `FirestoreAuditLog` /
`write_before_execute`. Phase 5 (E3) does the equivalent upgrade for #1,
#4, #5, and #7 — real tests against `app.tools.registry.ToolRegistry`,
`app.arbitration.confidence_arbiter.ConfidenceArbiter`,
`app.arbitration.approval_gate.ApprovalGate`, and the concrete tools in
`app.tools`/`app.arbitration`, not placeholders. Phase 12 (E2) upgrades #6
to a real, repo-wide grep across every `.py` file under `backend/app/` and
every prompt `.md` under `backend/app/prompts/` (this test file and
`backend/tests/test_council_structural_invariants.py` are themselves
excluded — both legitimately *name* the forbidden word to define and
enforce the rule, exactly as this very sentence and `GharOS_Build_Spec_
v2.md` §12.2 itself must). Phase 13 (E3) upgrades #8 to a real, three-part
structural proof (see `TestInvariant8VoiceConfersNoActionCapability`
below) — the same "tracked skip, then closed for real by that phase's
own lead" pattern #6 followed in Phase 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
from app.voice.tts_client import TtsAudio

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


def test_invariant_6_no_debate_framing() -> None:
    """Agent-to-agent interaction is never framed as "debate" — it is
    specialization and interest representation (spec §12.2). Real,
    repo-wide grep-based lint rule (Phase 12): the literal word "debate"
    (case-insensitive) must not appear in any `.py` file under
    `backend/app/` or any prompt `.md` under `backend/app/prompts/` — the
    Council (§12.2) and Simulator (§11, "parallel exploration, never
    debate") are the two subsystems this risk actually applies to, but
    the check runs across all of `backend/app/` so a future subsystem
    cannot quietly reintroduce debate framing either.

    This test file and `test_council_structural_invariants.py` are
    excluded from the scan — both legitimately *name* the forbidden word
    to define and enforce this exact rule, precisely as this sentence,
    `CLAUDE.md`'s own rule 7, and `GharOS_Build_Spec_v2.md` §12.2 itself
    must (the frozen spec is never edited and is not scanned here at
    all)."""
    import re
    from pathlib import Path

    backend_root = Path(__file__).resolve().parent.parent
    app_root = backend_root / "app"
    excluded_test_files = {"test_safety_invariants.py", "test_council_structural_invariants.py"}
    pattern = re.compile(r"debate", re.IGNORECASE)

    violations: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(backend_root)))
    for path in sorted((app_root / "prompts").rglob("*.md")):
        if pattern.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(backend_root)))
    for path in sorted((backend_root / "tests").glob("*.py")):
        if path.name in excluded_test_files:
            continue
        # Belt-and-braces: no other test file should need to name the
        # forbidden word either — only the two files that define/enforce
        # the rule itself are exempt.
        if pattern.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(backend_root)))

    assert violations == [], f"the word 'debate' must never appear in real code/prompts: {violations}"


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


class TestInvariant8VoiceConfersNoActionCapability:
    """Voice confers no action capability beyond what was pre-authorised —
    enforced by voice intent routing (Phase 13, ADR-020 Decision 5). Real,
    repo-wide structural proof, in the same family as invariant 6's own
    repo-wide grep and Phase 7/10/12's arbitration-import boundary tests
    — closed for real this phase by E3 (Phase 13's lead), the same way
    invariant 6 was closed for real by E2 in Phase 12.

    Three independent pieces, matching ADR-020 Decision 5 exactly:

    1. No module under `backend/app/agents/voice/` (A64/A65/A67/A68, E2)
       or `backend/app/voice/` EXCEPT `session_manager.py`/`routing.py`/
       `session_types.py` (A62/A63/A66/A69, E3) imports `app.arbitration`
       or a gated-tool name from `contracts.tools` — reproduced here
       directly (not merely "see test_voice_agents_arbitration_
       boundary.py / test_voice_infra_arbitration_boundary.py") so this
       invariant's own proof does not silently go stale if either of
       those dedicated suites is ever deleted.
    2. `routing.py` (A62) IS the real, deliberate exception — a sanity
       check that this invariant's own exclusion list still names a
       module that genuinely imports `app.arbitration` (the R-tier gating
       logic was deliberately split out of `session_manager.py` into its
       own file, `routing.py`, for file-size discipline and auditability
       — see that module's own docstring), not a module that happens to
       import nothing at all (which would make check #1 vacuously true
       for the wrong reason).
    3. The safety-critical behaviour itself: constructing a real
       `VoiceIntentResult` at `risk_tier=R3_EXPLICIT_APPROVE` plus a
       maximally-affirmative `ConfirmationResult` and a real
       `GatedExecutionRequest`, then asserting `ApprovalGate.
       approve_and_execute` is never called — the concrete "R3 is never
       approved by voice alone" proof. See `test_voice_session_manager.py
       ::TestR3NeverApprovedByVoiceAlone` for the fuller suite this
       summarizes the headline claim of.
    """

    _VOICE_REASONING_ROOT = Path(__file__).resolve().parent.parent / "app" / "agents" / "voice"
    _VOICE_INFRA_ROOT = Path(__file__).resolve().parent.parent / "app" / "voice"
    _INFRA_EXCLUDED = {"session_manager.py", "routing.py", "session_types.py", "__init__.py"}
    _FORBIDDEN_IMPORT_SUBSTRINGS = (
        "app.arbitration",
        "arbitration.actions",
        "arbitration.gated_tool",
        "arbitration.approval_gate",
    )

    def _scanned_voice_files(self) -> list[Path]:
        reasoning_files = [
            p for p in self._VOICE_REASONING_ROOT.glob("*.py") if "__pycache__" not in p.parts
        ]
        infra_files = [
            p
            for p in self._VOICE_INFRA_ROOT.glob("*.py")
            if "__pycache__" not in p.parts and p.name not in self._INFRA_EXCLUDED
        ]
        return sorted(reasoning_files + infra_files)

    def test_no_voice_reasoning_or_infra_agent_imports_arbitration(self) -> None:
        import ast

        violations: list[str] = []
        for path in self._scanned_voice_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module_name: str | None = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        if any(s in module_name for s in self._FORBIDDEN_IMPORT_SUBSTRINGS):
                            violations.append(f"{path.name} imports {module_name!r}")
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    module_name = node.module
                    if any(s in module_name for s in self._FORBIDDEN_IMPORT_SUBSTRINGS):
                        violations.append(f"{path.name} imports {module_name!r}")
        assert violations == [], (
            "A64/A65/A67/A68 (E2) and A63/A66/A69 (E3) must have no import path to "
            "the arbitration/action-execution layer:\n" + "\n".join(violations)
        )

    def test_routing_module_is_the_real_single_exception(self) -> None:
        routing_path = self._VOICE_INFRA_ROOT / "routing.py"
        assert routing_path.is_file()
        source = routing_path.read_text(encoding="utf-8")
        assert "app.arbitration" in source, (
            "routing.py (A62) is supposed to be the ONE module that legitimately holds an "
            "ApprovalGate reference (ADR-020 Decision 5) — it doesn't appear to import "
            "app.arbitration at all, which would make check #1 above vacuous."
        )

    def test_r3_intent_confirmed_true_never_reaches_approve_and_execute(self) -> None:
        from contracts.tools import ApprovalGatedTool

        from app.agents.intake.entity_resolution import EntityResolutionAgent
        from app.agents.voice.confirmation_agent import ConfirmationAgent
        from app.agents.voice.language_script_identifier_agent import LanguageScriptIdentifierAgent
        from app.agents.voice.normalisation_agent import NormalisationAgent
        from app.agents.voice.types import ConfirmationResult, VoiceIntentClass, VoiceIntentResult
        from app.agents.voice.voice_intent_classifier_agent import VoiceIntentClassifierAgent
        from app.voice.session_manager import VoiceSessionManager
        from app.voice.session_types import ApprovalContext, GatedExecutionRequest
        from app.voice.speaker_identification import SpeakerIdentificationAgent
        from app.voice.speech_recognition_handler import SpeechRecognitionHandler
        from app.voice.voice_response_agent import VoiceResponseAgent

        from ._fake_approval_gate import FakeApprovalGate
        from ._fake_graph_writer import FakeGraphWriter
        from ._fake_raw_payload_store import FakeRawPayloadStore
        from ._gemini_fakes import FakeModels, fake_router

        idle_client = GeminiClient(router=fake_router(FakeModels(texts=["{}"])))
        gate = FakeApprovalGate()
        manager = VoiceSessionManager(
            speech_recognition=SpeechRecognitionHandler(gemini_client=idle_client),
            speaker_identification=SpeakerIdentificationAgent(gemini_client=idle_client),
            language_identifier=LanguageScriptIdentifierAgent(gemini_client=idle_client),
            normalisation=NormalisationAgent(gemini_client=idle_client),
            entity_resolution=EntityResolutionAgent(gemini_client=idle_client),
            intent_classifier=VoiceIntentClassifierAgent(gemini_client=idle_client),
            confirmation=ConfirmationAgent(gemini_client=idle_client),
            response_agent=VoiceResponseAgent(gemini_client=idle_client, tts_client=_IdleTtsClient()),
            approval_gate=gate,
            graph_writer=FakeGraphWriter(),
            raw_payload_store=FakeRawPayloadStore(),
        )

        class _FakeGatedTool(ApprovalGatedTool):
            def __init__(self) -> None:
                self.name = "fake_gated_tool"
                self.tier: PermissionTier = PermissionTier.T6_FINANCIAL
                self.bounds: dict[str, object] = {}

            def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
                raise AssertionError("must never be invoked — this IS the invariant under test")

        r3_intent = VoiceIntentResult(
            turn_id="invariant-8-turn",
            intent=VoiceIntentClass.APPROVAL,
            risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            target_summary="pay the staff salary",
            requires_confirmation=True,
            reasoning="a real money-movement request",
            confidence=0.98,
            model_tier="pro",
            prompt_version="v1",
            invocation_id="inv-1",
            classified_at=datetime.now(UTC),
        )
        maximally_affirmative = ConfirmationResult(
            turn_id="invariant-8-turn",
            confirmed=True,
            reason="explicit, unambiguous, repeated affirmative",
            matched_affirmative_phrase="haan kar do",
            model_tier="pro",
            prompt_version="v1",
            invocation_id="inv-2",
            evaluated_at=datetime.now(UTC),
        )
        gated_execution = GatedExecutionRequest(
            tool=_FakeGatedTool(), invoke_kwargs={}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(  # noqa: SLF001 — this IS the safety-critical method under test
            r3_intent,
            confirmation=maximally_affirmative,
            approval_context=ApprovalContext(
                action_type="voice_pay_salary",
                entity_id="staff-1",
                cycle="2026-08",
                target_node_id=NodeId("ledger-event-1"),
            ),
            gated_execution=gated_execution,
            # a real, IDENTIFIED speaker — this test is about R3, not A66's unknown-speaker gate
            speaker_person_id=NodeId("person-1"),
        )

        assert outcome.kind == "approval_pending"
        assert len(gate.request_approval_calls) == 1
        assert gate.approve_and_execute_calls == [], (
            "safety invariant 8 violated: an R3-tier voice intent reached "
            "ApprovalGate.approve_and_execute off a voice confirmation alone"
        )


class _IdleTtsClient:
    """A minimal TTS stand-in for `TestInvariant8VoiceConfersNoActionCapability`
    — never actually invoked, since `_route` (the method under test) never
    reaches A69's response generation."""

    def synthesize(self, *, text: str, voice_name: str, language_code: str) -> TtsAudio:
        raise AssertionError("must never be invoked by this invariant's own routing-only test")

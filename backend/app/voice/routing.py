"""A62's own R-tier gating logic — split out of `session_manager.py` into
its own module for two reasons: file-size discipline (gharos-standards:
"files <= ~500 lines, without a stated reason" — `session_manager.py`'s
real pipeline-orchestration code alone already approaches that on its
own) and, more importantly, **auditability**: this is the single
safety-critical decision point Gate 13 actually tests (ADR-020 Decision
5), and putting it in one small, dedicated file makes the complete
request_approval/approve_and_execute code path reviewable in one place,
with nothing else competing for the reader's attention.

**This module is the other deliberate exception to safety invariant 8**
alongside `session_manager.py` itself (ADR-020 Decision 5 item 3) — it
legitimately imports `app.arbitration` because it is the code that calls
`ApprovalGate.request_approval`/`approve_and_execute`. `backend/tests/
test_voice_infra_arbitration_boundary.py` and `backend/tests/test_safety_
invariants.py::TestInvariant8VoiceConfersNoActionCapability` both name
this file (alongside `session_manager.py`/`session_types.py`) as excluded
from the "no arbitration import" scan for exactly this reason.

See `session_manager.py`'s own module docstring for the full statement of
what each risk tier does — this module is the implementation, not a
second copy of that policy description.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import structlog
from contracts.actions import EvidenceBundle, RiskTier, tier_at_least
from contracts.graph_types import AgentId, ApprovalRequest, NodeId
from contracts.tools import ApprovalGatedTool

from app.agents.voice.types import ConfirmationResult, VoiceIntentClass, VoiceIntentResult
from app.arbitration.types import ApprovalOutcome, ArbiterDecision, ArbiterResult, ProposedAction

from .session_types import (
    ApprovalContext,
    GatedExecutionRequest,
    VoiceRoutingCallbacks,
    VoiceRoutingOutcome,
)

logger = structlog.get_logger(__name__)


class ApprovalGateProtocol(Protocol):
    """Structural subset of `app.arbitration.approval_gate.ApprovalGate`
    this module actually calls — lets a test inject a lightweight fake
    without constructing a real, Firestore-backed `ApprovalGate`, while
    the real `ApprovalGate` satisfies this shape unchanged."""

    def request_approval(
        self, arbiter_result: ArbiterResult, *, now: datetime | None = None
    ) -> ApprovalRequest: ...

    def approve_and_execute(
        self,
        *,
        arbiter_result: ArbiterResult,
        approval_request: ApprovalRequest,
        approved_by_person_id: NodeId,
        tool: ApprovalGatedTool,
        invoke_kwargs: dict[str, object],
        now: datetime | None = None,
    ) -> ApprovalOutcome: ...


def _consequence_if_wrong(intent: VoiceIntentResult) -> str:
    return (
        f"Executing '{intent.target_summary}' on a mis-heard or mis-confirmed voice request could "
        "commit the household to an unintended external action, communication, or payment."
    )


def default_approval_context(turn_id: str, intent: VoiceIntentResult, *, now: datetime) -> ApprovalContext:
    return ApprovalContext(
        action_type=f"voice_{intent.intent.value}",
        entity_id=f"voice-turn:{turn_id}",
        cycle=now.strftime("%Y-%m"),
        target_node_id=NodeId(f"voice-turn:{turn_id}"),
    )


_UNKNOWN_SPEAKER_GATE_FLOOR = RiskTier.R2_APPROVE
"""spec §15.11 A66's own failure mode: "unknown speaker -> restrict to
R0/R1 actions only; never accept an approval from an unidentified
voice." Any risk tier at or above this floor (R2/R3/R4) is refused
outright when the speaker is unidentified — checked before a read-back/
confirmation is even offered (`session_manager.py`'s own early call to
`check_speaker_authorization`), and again here inside `route()` itself as
defense in depth for the one path (`DECISION_TRIGGER`) that never goes
through a confirmation step at all, and for the post-confirmation R2/R3
call `session_manager._process_confirmation_reply` makes."""


def _unknown_speaker_refusal(intent: VoiceIntentResult) -> VoiceRoutingOutcome:
    return VoiceRoutingOutcome(
        kind="refused_unknown_speaker",
        risk_tier=intent.risk_tier,
        approval_request_id=None,
        note=(
            "an unidentified speaker attempted an action at or above R2 — refused outright, "
            "per spec's own A66 failure mode ('never accept an approval from an unidentified voice')"
        ),
    )


# ADR-023 §7 addendum (Phase 14.5): `ingest.scan_mailbox` carries no RiskTier,
# so the R2 floor in `check_speaker_authorization` never gates it — but a
# mailbox scan reads the household's private Gmail/Outlook, so it is gated
# here as an identity-gated read: an unidentified / unenrolled speaker is
# declined and asked to identify, and no ingestion run is started.
def _scan_needs_identification_refusal(intent: VoiceIntentResult) -> VoiceRoutingOutcome:
    return VoiceRoutingOutcome(
        kind="declined_needs_identification",
        risk_tier=None,
        approval_request_id=None,
        note=(
            "ingest.scan_mailbox requested by an unidentified speaker — declined; a mailbox scan "
            "reads the household's private Gmail/Outlook and is gated on an identified, enrolled "
            "speaker (identity-gated read, ADR-023 §7 addendum). No ingestion run started."
        ),
    )


class VoiceRouter:
    """Owns exactly one thing: turning a classified `VoiceIntentResult`
    (plus an optional `ConfirmationResult`) into the real, gated outcome
    spec §14.5/§14.6 and ADR-020 Decision 5 require. Dependency-injected
    on an `ApprovalGateProtocol` and the caller's `VoiceRoutingCallbacks`
    — holds no pipeline state of its own (that stays in `session_manager.
    VoiceSessionManager`, the one place multi-turn confirmation context
    lives).
    """

    def __init__(self, *, approval_gate: ApprovalGateProtocol, callbacks: VoiceRoutingCallbacks) -> None:
        self._approval_gate = approval_gate
        self._callbacks = callbacks

    def check_speaker_authorization(
        self, intent: VoiceIntentResult, *, speaker_person_id: NodeId | None
    ) -> VoiceRoutingOutcome | None:
        """spec §15.11 A66's own failure mode, made structural: "unknown
        speaker -> restrict to R0/R1 actions only; never accept an
        approval from an unidentified voice."

        Returns:
            A real `VoiceRoutingOutcome(kind="refused_unknown_speaker")`
            when `speaker_person_id is None` (A66's own well-defined
            "unknown speaker" signal — see `speaker_identification.py`)
            and `intent.risk_tier` is R2 or above. The caller
            (`session_manager.py`) must stop right there — never offer a
            read-back/confirmation, never reach the gated path below.
            A `VoiceRoutingOutcome(kind="declined_needs_identification")`
            when the intent is `INGEST_SCAN_MAILBOX` and the speaker is
            unidentified — a mailbox scan is an identity-gated read of the
            household's private mail (ADR-023 §7 addendum), even though
            the intent carries no risk tier.
            `None` when the turn may proceed normally: a known speaker,
            or a non-scan intent carrying no risk tier at all (capture/
            intention/query/correction), or a `COMMAND` at R0/R1 — spec's
            own line restricts *to* R0/R1 for an unidentified speaker, it
            does not block everything.
        """
        if speaker_person_id is not None:
            return None
        if intent.intent is VoiceIntentClass.INGEST_SCAN_MAILBOX:
            # Identity-gated read (ADR-023 §7 addendum): an unidentified /
            # unenrolled speaker may not trigger a scan of the household's
            # private mailbox. `speaker_person_id is None` here means A66
            # matched no enrolled voiceprint.
            logger.warning("voice.routing.scan_mailbox_declined_unidentified_speaker", turn_id=intent.turn_id)
            return _scan_needs_identification_refusal(intent)
        if intent.risk_tier is None:
            return None
        if not tier_at_least(intent.risk_tier, _UNKNOWN_SPEAKER_GATE_FLOOR):
            return None
        logger.warning(
            "voice.routing.refused_unknown_speaker",
            intent=intent.intent.value,
            risk_tier=intent.risk_tier.value,
        )
        return _unknown_speaker_refusal(intent)

    def route(
        self,
        intent: VoiceIntentResult,
        *,
        confirmation: ConfirmationResult | None,
        approval_context: ApprovalContext,
        gated_execution: GatedExecutionRequest | None,
        speaker_person_id: NodeId | None,
    ) -> VoiceRoutingOutcome:
        """Routes one classified intent. See `session_manager.py`'s
        module docstring for the complete per-tier policy this
        implements.

        Args:
            speaker_person_id: A66's real speaker-identification result
                for this turn (`None` for an unidentified speaker) —
                checked first, unconditionally, via `check_speaker_
                authorization`, before any other routing decision.
        """
        refusal = self.check_speaker_authorization(intent, speaker_person_id=speaker_person_id)
        if refusal is not None:
            return refusal

        if intent.intent is VoiceIntentClass.INGEST_SCAN_MAILBOX:
            # ADR-023 §7: a read-only "scan my Gmail and Outlook" trigger.
            # Reached only for an identified, enrolled speaker (the
            # unidentified case was declined in `check_speaker_
            # authorization` above). Hands off to the ingestion
            # orchestrator via `on_scan_mailbox(turn_id)` — never a tool,
            # never the Approval Gate, carries no RiskTier. Invariant #8
            # holds: nothing on this path can reach a T4/T5/T6 tool.
            scan_callback = self._callbacks.on_scan_mailbox
            if scan_callback is None:
                logger.info("voice.routing.no_scan_mailbox_callback_wired", turn_id=intent.turn_id)
            else:
                scan_callback(intent.turn_id)
            return VoiceRoutingOutcome(
                kind="handed_off",
                risk_tier=None,
                approval_request_id=None,
                note="ingest.scan_mailbox - read-only ingestion trigger, no action (ADR-023)",
            )

        if intent.intent is VoiceIntentClass.DECISION_TRIGGER:
            self._invoke_callback(self._callbacks.on_decision_trigger, intent)
            return VoiceRoutingOutcome(
                kind="escalated_to_council",
                risk_tier=RiskTier.R4_ESCALATE_ONLY,
                approval_request_id=None,
                note="R4 is never resolved by voice — handed to Council convening only.",
            )

        handoff_intents = (
            VoiceIntentClass.CAPTURE,
            VoiceIntentClass.INTENTION,
            VoiceIntentClass.QUERY,
            VoiceIntentClass.CORRECTION,
        )
        if intent.intent in handoff_intents:
            callback = {
                VoiceIntentClass.CAPTURE: self._callbacks.on_capture,
                VoiceIntentClass.INTENTION: self._callbacks.on_intention,
                VoiceIntentClass.QUERY: self._callbacks.on_query,
                VoiceIntentClass.CORRECTION: self._callbacks.on_correction,
            }[intent.intent]
            self._invoke_callback(callback, intent)
            return VoiceRoutingOutcome(
                kind="handed_off",
                risk_tier=None,
                approval_request_id=None,
                note=f"handed off as {intent.intent.value}",
            )

        # COMMAND or APPROVAL — the only two classes A67 ever attaches a
        # risk tier to (see app.agents.voice.voice_intent_classifier_agent).
        if intent.risk_tier in (RiskTier.R0_SILENT, RiskTier.R1_NOTIFY):
            self._invoke_callback(self._callbacks.on_command_r0_r1, intent)
            return VoiceRoutingOutcome(
                kind="executed_r0_r1",
                risk_tier=intent.risk_tier,
                approval_request_id=None,
                note="executed directly",
            )

        return self._route_gated(
            intent,
            confirmation=confirmation,
            approval_context=approval_context,
            gated_execution=gated_execution,
        )

    def _route_gated(
        self,
        intent: VoiceIntentResult,
        *,
        confirmation: ConfirmationResult | None,
        approval_context: ApprovalContext,
        gated_execution: GatedExecutionRequest | None,
    ) -> VoiceRoutingOutcome:
        """R2/R3 only. Constructs a real `ArbiterResult` and calls
        `ApprovalGate.request_approval` unconditionally for both tiers —
        `approve_and_execute` is called ONLY from the R2 branch below,
        never the R3 one. This is the concrete, structural proof behind
        this module's own docstring claim."""
        proposed = ProposedAction(
            action_type=approval_context.action_type,
            entity_id=approval_context.entity_id,
            cycle=approval_context.cycle,
            target_node_id=approval_context.target_node_id,
            confidence=intent.confidence,
            involves_hard_constraint=False,
            reasoning=intent.reasoning,
            evidence_consulted=(intent.target_summary,),
            consequence_if_wrong=_consequence_if_wrong(intent),
            proposed_by=AgentId("A67"),
            source_ref=None,
        )
        assert intent.risk_tier is not None  # only called for APPROVAL, which always carries a tier
        arbiter_result = ArbiterResult(
            proposed_action=proposed,
            decision=ArbiterDecision.APPROVE,
            final_risk_tier=intent.risk_tier,
            confidence=intent.confidence,
            evidence_bundle=EvidenceBundle(
                proposed_action=f"{proposed.action_type} ({proposed.entity_id})",
                reasoning=proposed.reasoning,
                evidence_consulted=proposed.evidence_consulted,
                confidence=proposed.confidence,
                consequence_if_wrong=proposed.consequence_if_wrong,
            ),
            escalated_to_pro=False,
            discard_reason=None,
        )
        approval_request = self._approval_gate.request_approval(arbiter_result)

        if intent.risk_tier is RiskTier.R2_APPROVE:
            if confirmation is not None and confirmation.confirmed and gated_execution is not None:
                self._approval_gate.approve_and_execute(
                    arbiter_result=arbiter_result,
                    approval_request=approval_request,
                    approved_by_person_id=gated_execution.approved_by_person_id,
                    tool=gated_execution.tool,
                    invoke_kwargs=gated_execution.invoke_kwargs,
                )
                return VoiceRoutingOutcome(
                    kind="approved_and_executed",
                    risk_tier=RiskTier.R2_APPROVE,
                    approval_request_id=approval_request.id,
                    note="R2 approved and executed end-to-end via voice confirmation.",
                )
            return VoiceRoutingOutcome(
                kind="approval_pending",
                risk_tier=RiskTier.R2_APPROVE,
                approval_request_id=approval_request.id,
                note="R2 approval request written; awaiting execution wiring or the visual approval queue.",
            )

        # R3_EXPLICIT_APPROVE: request_approval only, above — no further
        # branch here calls approve_and_execute, under any condition.
        return VoiceRoutingOutcome(
            kind="approval_pending",
            risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            approval_request_id=approval_request.id,
            note="R3 is never approved by voice alone — queued for your approval on the app.",
        )

    def _invoke_callback(self, callback: object, intent: VoiceIntentResult) -> None:
        if callback is None:
            logger.info("voice.routing.no_callback_wired", intent=intent.intent.value)
            return
        callback(intent)  # type: ignore[operator]  # VoiceIntentCallback, narrowed by caller construction


__all__ = ["ApprovalGateProtocol", "VoiceRouter", "default_approval_context"]

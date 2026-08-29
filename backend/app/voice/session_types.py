"""Shapes local to `session_manager.py` (A62) ONLY — the orchestrator's own
routing/gating vocabulary, deliberately kept OUT of `types.py`.

**Why a separate module, not just more of `types.py`:** `types.py` is
imported by `speech_recognition_handler.py` (A63), `speaker_
identification.py` (A66), and `voice_response_agent.py` (A69) —
safety invariant 8's own structural proof
(`backend/tests/test_voice_infra_arbitration_boundary.py`) requires that
none of those three modules import `app.arbitration` or a gated-tool name
from `contracts.tools`, at all, transitively included. This module imports
`contracts.tools.ApprovalGatedTool` (needed to type an R2 gated-execution
request) and `contracts.actions.RiskTier` — importing either from
`types.py` would leak them into A63/A66/A69 through their own `from
.types import ...` line, silently defeating the very boundary this phase
must prove. Keeping this vocabulary in its own file, imported only by
`session_manager.py` (the one deliberate exception — ADR-020 Decision 5),
is what makes that boundary a real, checkable fact rather than a
convention someone could break by accident in a future edit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from contracts.actions import RiskTier
from contracts.graph_types import NodeId
from contracts.tools import ApprovalGatedTool

from app.agents.voice.types import ConfirmationResult, ReadbackResult, VoiceIntentResult

VoiceIntentCallback = Callable[[VoiceIntentResult], None]
"""One hand-off callback's shape — every field of `VoiceRoutingCallbacks`
below is either this or `None`."""


@dataclass(frozen=True, slots=True)
class ApprovalContext:
    """The real graph-entity specifics one R2/R3 approval request needs
    (`app.arbitration.types.ProposedAction`'s own required fields) —
    supplied by whichever downstream subsystem the voice command actually
    targets. When the caller has no such specifics yet (a generic voice
    command with no wired downstream execution path this phase), `session_
    manager.VoiceSessionManager` falls back to synthetic-but-honest
    defaults derived from `turn_id` alone — the approval request still
    gets written for real, it simply cannot yet `ACTS_ON` a specific
    graph entity beyond a placeholder one.
    """

    action_type: str
    entity_id: str
    cycle: str
    target_node_id: NodeId


@dataclass(frozen=True, slots=True)
class GatedExecutionRequest:
    """Supplied by the caller ONLY for an R2-tier intent it wants closed
    end-to-end in this same turn (ADR-020 Decision 5 item 3: "for R2,
    after `ConfirmationResult.confirmed is True`, you MAY call
    `ApprovalGate.approve_and_execute` directly... full voice approval
    end-to-end for R2 is correct"). **Never consulted at all for R3** —
    see `session_manager.VoiceSessionManager._route_gated` for the
    structural proof this is not merely "not used" but literally
    unreachable code for that tier."""

    tool: ApprovalGatedTool
    invoke_kwargs: dict[str, object]
    approved_by_person_id: NodeId


@dataclass(frozen=True, slots=True)
class VoiceRoutingCallbacks:
    """Injectable hand-off points to the subsystems each non-gated intent
    class routes to (spec §14.4's own pipeline table). Each is a plain
    `Callable` the caller wires to the real subsystem's own entry point —
    genuinely integrating "hand to the Consequence Engine" / "hand to
    Intention->Action" / "convene the Council" is each of those
    subsystems' own already-built entry point (earlier phases), reached
    through whatever real adapter the caller constructs; this package's
    job (and Gate 13's own test target) is the R-tier gating logic in
    `_route_gated`, not re-building those subsystems' call signatures.
    Every field defaults to `None` (a no-op, logged) so a `VoiceSession
    Manager` is fully constructible and testable before every downstream
    integration exists."""

    on_capture: VoiceIntentCallback | None = None
    on_intention: VoiceIntentCallback | None = None
    on_query: VoiceIntentCallback | None = None
    on_correction: VoiceIntentCallback | None = None
    on_decision_trigger: VoiceIntentCallback | None = None
    on_command_r0_r1: VoiceIntentCallback | None = None
    on_scan_mailbox: Callable[[str], None] | None = None
    """Phase 14.5 / ADR-023 §7 — the hand-off for A67's
    `ingest.scan_mailbox` intent, a read-only "scan my Gmail and Outlook"
    ingestion trigger. Deliberately typed `Callable[[str], None]`, NOT
    `VoiceIntentCallback`: it is structurally distinct from every
    action-routing field above and receives only the `turn_id` (a
    `str`), which is all E3's orchestrator wiring needs to build
    `IngestionRequest(sources=(GMAIL, OUTLOOK), window=24h,
    principal=<the household's single connected principal>,
    triggered_by="voice", idempotency_scope=f"voice-turn:{turn_id}")`.
    This intent carries no `RiskTier` and must never reach
    `VoiceRouter._route_gated`, `ApprovalGate`, or any tool — invariant
    #8 holds because nothing on this path can reach a T4/T5/T6 tool.
    `None` (a logged no-op) until E3 wires the ingestion orchestrator."""


@dataclass(frozen=True, slots=True)
class VoiceRoutingOutcome:
    """What `routing.VoiceRouter.route` actually did for one classified
    turn — the direct, assertable proof every structural safety test in
    this phase checks against."""

    kind: Literal[
        "executed_r0_r1",
        "handed_off",
        "escalated_to_council",
        "approval_pending",
        "approved_and_executed",
        "refused_unknown_speaker",
        "declined_needs_identification",
    ]
    """`"refused_unknown_speaker"` (spec §15.11 A66's own failure mode:
    "unknown speaker -> restrict to R0/R1 actions only; never accept an
    approval from an unidentified voice") is reachable only for `risk_
    tier` at or above R2 with no identified speaker — see `routing.
    VoiceRouter.check_speaker_authorization`.

    `"declined_needs_identification"` (Phase 14.5, ADR-023 §7 addendum) is
    the identity gate on `VoiceIntentClass.INGEST_SCAN_MAILBOX`: a mailbox
    scan reads the household's private Gmail/Outlook, so it is treated as
    an identity-gated read — an unidentified / unenrolled speaker is
    declined and asked to identify, and NO ingestion run is started. The
    intent carries no `RiskTier`, so `check_speaker_authorization`'s R2
    floor never fires for it; this branch is the explicit gate instead."""
    risk_tier: RiskTier | None
    approval_request_id: NodeId | None
    note: str


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """A62's own multi-turn state: a not-yet-confirmed intent, held
    between the turn that triggered a read-back and the household
    member's next spoken reply. Cleared unconditionally at the end of
    that next turn — confirmed or not, and also on any corrupted turn
    (spec's own A62 failure mode: never act on a partial/stale
    confirmation state)."""

    intent_result: VoiceIntentResult
    readback: ReadbackResult
    approval_context: ApprovalContext
    gated_execution: GatedExecutionRequest | None
    original_audio: bytes
    original_audio_mime_type: str
    speaker_person_id: NodeId | None
    original_language: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    """`VoiceSessionManager.process_turn`'s complete, real outcome for one
    turn — everything `api.voice_router` needs to translate into ADR-020
    Decision 3's outgoing WebSocket frames."""

    turn_id: str
    kind: Literal["needs_clarification", "confirmation_requested", "completed", "discarded"]
    raw_text: str | None
    spoken_response_text: str | None
    response_audio_bytes: bytes | None
    response_audio_mime_type: str | None
    response_language: str | None
    confirmation: ConfirmationResult | None
    routing_outcome: VoiceRoutingOutcome | None
    discard_reason: str | None = None
    source_document_id: NodeId | None = None
    extra: dict[str, str] = field(default_factory=dict)


__all__ = [
    "ApprovalContext",
    "GatedExecutionRequest",
    "PendingConfirmation",
    "TurnResult",
    "VoiceRoutingCallbacks",
    "VoiceRoutingOutcome",
]

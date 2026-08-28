"""`VoiceCallTool` — the real T5 outbound-voice tool (spec §16.2's T5 row:
"outbound voice caller — approval-gated, bounds-enforced, disclosure-
enforced"), PHASES.md Phase 10.

Follows `gated_tool.ReferenceGatedTool` / `payment_tool.SandboxPaymentTool`'s
exact established shape (this module's siblings, same package): check
idempotency reservation first, perform the effect, record the result. The
effect here is real and fully wired end to end — a real, live, multi-turn
conversation (`app.agents.concierge.voice_call_agent.
VoiceCallConversationEngine`, this tool's only dependency for *conducting*
the call), a real transcript durably stored (`RawPayloadStore` +
`GraphWriter`, exactly `SandboxPaymentTool`'s own "internal bookkeeping is
fully real" precedent) — the only thing genuinely sandboxed is *who is on
the other end of the call* (`app.agents.concierge.sandbox_counterparty.
SandboxCounterparty`, a real second LLM agent, never a real business —
ADR-016, spec §23).

## What "sandbox" means here (this phase's own instructions — mirrors
## `payment_tool.py`'s own "what sandbox means here" section)

There is no telephony SDK import anywhere in this file — no Twilio, no
SIP client, nothing capable of dialing a real phone number even in
principle. That is deliberate for the same two reasons `SandboxPaymentTool`
gives for holding no payment-rail credential: (1) there is no real
telephony credential in this project to begin with, and building a fake
one would only add unverifiable theatre; (2) the point of this phase is
proving the safety machinery (bounds enforcement, mandatory disclosure,
verification-before-recording, the approval gate itself) — every one of
those is fully real and fully exercised by this tool, end to end, against
a real independently-reasoning counterparty; only the literal telephone
line is sandboxed. ADR-016 additionally documents *why* even the
counterparty's own speech is text/transcript this phase, not synthesized
audio — that is a separate, explicit scope boundary (Phase 13's job), not
this tool's own sandboxing choice.

## Disclosure — see `voice_call_agent.py`'s module docstring for the full
argument that turn zero is code-composed, never model-generated. This
tool's own contribution to that guarantee: `CallOutcomeReport.
disclosure_given` is hard-set to `True` unconditionally below — there is
no code path in this file that could set it to `False`, because the
underlying `CallConversationResult.turns[0]` is *always*
`voice_call_agent._disclosure_opening`'s output by construction (the
engine has no other way to start a conversation).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from contracts.actions import ActionResult
from contracts.errors import OutOfBounds, ToolFailure
from contracts.graph_types import (
    Derivation,
    NodeId,
    Provenance,
    SourceDocument,
    SourceRef,
)
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import ApprovalGatedTool, PermissionTier

from app.agents.concierge.sandbox_counterparty import SandboxCounterparty
from app.agents.concierge.types import CallBrief, CallConversationResult, CallOutcomeReport, CallTurn
from app.agents.concierge.voice_call_agent import AGENT_ID as A54_AGENT_ID
from app.agents.concierge.voice_call_agent import VoiceCallConversationEngine
from app.persistence.raw_payload_store import RawPayloadStore

_TRANSCRIPT_CONTENT_TYPE = "text/plain"
_TRANSCRIPT_REGION = "whole-transcript"
_SOURCE_DOCUMENT_CHANNEL = "voice_call_outbound"
"""ADR-016's exact named convention for this channel value."""
_SOURCE_DOCUMENT_TYPE = "voice_call_transcript"
"""Not one of the Document-Type Registry's 14 registered types (spec
§5.4) — deliberately: this `SourceDocument` is never produced via the
intake pipeline (A2 Intake Router never classifies it; it is written
directly by this tool, the same way `SandboxPaymentTool` writes a
`LedgerEvent` directly rather than through an ingestion adapter). Set to
this explicit, honest label rather than `None` ("pending classification")
since nothing will ever classify it — `None` here would misleadingly
imply a classification step is still owed."""


def _render_transcript(turns: tuple[CallTurn, ...]) -> str:
    return "\n".join(f"[{turn.turn_index}] {turn.speaker}: {turn.utterance}" for turn in turns)


def _serialize_report(report: CallOutcomeReport) -> str:
    return json.dumps(
        {
            "call_id": report.call_id,
            "target_provider_id": str(report.target_provider_id),
            "transcript_source_document_id": str(report.transcript_source_document_id),
            "disclosure_given": report.disclosure_given,
            "claimed_slot": report.claimed_slot.isoformat() if report.claimed_slot is not None else None,
            "claimed_outcome_summary": report.claimed_outcome_summary,
            "out_of_bounds_encountered": report.out_of_bounds_encountered,
            "requires_human_callback": report.requires_human_callback,
        }
    )


def _deserialize_report(text: str) -> CallOutcomeReport:
    data = json.loads(text)
    claimed_slot = data["claimed_slot"]
    return CallOutcomeReport(
        call_id=data["call_id"],
        target_provider_id=NodeId(data["target_provider_id"]),
        transcript_source_document_id=NodeId(data["transcript_source_document_id"]),
        disclosure_given=data["disclosure_given"],
        claimed_slot=datetime.fromisoformat(claimed_slot) if claimed_slot is not None else None,
        claimed_outcome_summary=data["claimed_outcome_summary"],
        out_of_bounds_encountered=data["out_of_bounds_encountered"],
        requires_human_callback=data["requires_human_callback"],
    )


class VoiceCallTool(ApprovalGatedTool):
    """T5. Constructed and registered only from `backend/app/arbitration/`
    via `gated_tool.register_gated_tool` — the same rule every T4/T5/T6
    tool in this codebase follows, checked structurally by
    `app.tools.registry.ToolRegistry.register`, not by convention.
    """

    def __init__(
        self,
        *,
        conversation_engine: VoiceCallConversationEngine,
        graph_writer: GraphWriter,
        raw_payload_store: RawPayloadStore,
        idempotency_store: IdempotencyStore,
        bounds: dict[str, object],
        name: str = "voice_call_tool",
    ) -> None:
        """Args:
        conversation_engine: conducts the actual turn-by-turn call —
            holds no action credential of its own (see that module's
            docstring); this tool is the only caller permitted to hand it
            both a real `CallBrief` and a real `SandboxCounterparty` and
            trust its output enough to write a graph record from it.
        graph_writer: writes the transcript `SourceDocument` — real,
            provenance-guarded, exactly `GraphWriteTool`'s own underlying
            dependency.
        raw_payload_store: durably stores the real transcript text,
            exactly `SandboxPaymentTool`'s sibling dependencies' shape
            (dependency-injected, no module-level singleton).
        idempotency_store: the same `contracts.repositories.
            IdempotencyStore` every T3+ tool in this codebase uses.
        bounds: authorised bounds (spec §13.3) checked by this tool's own
            `check_bounds` override — richer than exact-match, mirroring
            `SandboxPaymentTool.check_bounds`'s own precedent for a
            domain-specific check. Recognised keys: `"target_provider_id"`
            (exact match against `kwargs["brief"].target_provider_id`),
            `"price_ceiling_max"` (ceiling — `brief.price_ceiling` must be
            `None` or `<=` this), `"date_range"` (a `(start, end)` tuple —
            `brief.date_range` must fall entirely within it). Any bound
            key absent from `self.bounds` is unrestricted.
        """
        self.name = name
        self.tier: PermissionTier = PermissionTier.T5_VOICE_OUTBOUND
        self.bounds = bounds
        self._engine = conversation_engine
        self._writer = graph_writer
        self._raw_payload_store = raw_payload_store
        self._idempotency_store = idempotency_store

    def check_bounds(self, **kwargs: object) -> None:
        """Raises `contracts.errors.OutOfBounds` on the first bound this
        invocation's `brief` violates. This runs BEFORE any conversation
        is conducted — Gate 10's "approval fires before any call" made
        literal: an out-of-scope `CallBrief` never even reaches
        `conversation_engine.run_conversation`.
        """
        brief = kwargs.get("brief")
        if not isinstance(brief, CallBrief):
            return  # missing/malformed brief surfaces as ToolFailure in invoke_idempotent, not here

        target_provider_id = self.bounds.get("target_provider_id")
        if target_provider_id is not None and str(brief.target_provider_id) != str(target_provider_id):
            raise OutOfBounds(
                bound_name="target_provider_id",
                requested=str(brief.target_provider_id),
                authorised=str(target_provider_id),
            )

        price_ceiling_max = self.bounds.get("price_ceiling_max")
        if price_ceiling_max is not None and brief.price_ceiling is not None:
            if not isinstance(price_ceiling_max, int | float) or brief.price_ceiling > price_ceiling_max:
                raise OutOfBounds(
                    bound_name="price_ceiling_max",
                    requested=str(brief.price_ceiling),
                    authorised=str(price_ceiling_max),
                )

        authorised_range = self.bounds.get("date_range")
        if authorised_range is not None:
            if (
                not isinstance(authorised_range, tuple)
                or len(authorised_range) != 2
                or not isinstance(authorised_range[0], datetime)
                or not isinstance(authorised_range[1], datetime)
            ):
                raise ToolFailure(
                    tool_name=self.name,
                    reason="'date_range' bound must be a (datetime, datetime) tuple",
                    retryable=False,
                )
            auth_start, auth_end = authorised_range
            requested_start, requested_end = brief.date_range
            if requested_start < auth_start or requested_end > auth_end:
                raise OutOfBounds(
                    bound_name="date_range",
                    requested=f"{requested_start.isoformat()}..{requested_end.isoformat()}",
                    authorised=f"{auth_start.isoformat()}..{auth_end.isoformat()}",
                )

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Places (conducts, in this phase's real-conversation sense —
        ADR-016) one outbound call and returns a `CallOutcomeReport`.

        Args (via kwargs):
            brief: the real `CallBrief` (E2's A53 output) this call is
                authorised against.
            counterparty: the real `SandboxCounterparty` on the other end
                — dependency-injected per invocation (mirrors this
                phase's dispatch: "never a fixture the calling agent's
                own code effectively wrote both sides of" — the caller
                supplies which independently-behaving persona this call
                reaches, this tool never constructs one itself).

        Returns:
            `ActionResult.success(report)` where `report` is a real
            `CallOutcomeReport` — **not stringified**, unlike
            `SandboxPaymentTool`'s own `result_ref` convention, because
            E2's A55 needs the full structured report, not a graph-node
            reference to re-fetch it from. The idempotency store itself
            still only ever holds a `str` (JSON-serialized) per
            `contracts.repositories.IdempotencyStore`'s own contract; a
            replay is deserialized back into a real `CallOutcomeReport`
            before being returned, so every caller sees the same shape on
            both the first call and a replay.

        Raises:
            contracts.errors.OutOfBounds: `brief` violated `self.bounds` —
                no conversation is attempted at all.
            contracts.errors.ToolFailure: `brief`/`counterparty` missing
                or malformed, or the underlying conversation engine raised
                (e.g. `app.reasoning.errors.GeminiCallFailed` from the
                counterparty's own call) — never reinterpreted as success
                (safety invariant #7).
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(_deserialize_report(cached_result_ref))

        self.check_bounds(**kwargs)

        brief = kwargs.get("brief")
        counterparty = kwargs.get("counterparty")
        if not isinstance(brief, CallBrief):
            raise ToolFailure(tool_name=self.name, reason="'brief' (CallBrief) is required", retryable=False)
        if not isinstance(counterparty, SandboxCounterparty):
            raise ToolFailure(
                tool_name=self.name,
                reason="'counterparty' (SandboxCounterparty) is required",
                retryable=False,
            )

        try:
            conversation_result = self._engine.run_conversation(brief=brief, counterparty=counterparty)
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, matching payment_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        report = self._write_report(brief=brief, conversation_result=conversation_result)

        self._idempotency_store.record_result(idempotency_key, _serialize_report(report))
        return ActionResult.success(report)

    def _write_report(
        self, *, brief: CallBrief, conversation_result: CallConversationResult
    ) -> CallOutcomeReport:
        call_id = f"call:{uuid.uuid4().hex}"
        doc_id = NodeId(f"doc:{uuid.uuid4().hex}")
        now = datetime.now(UTC)

        transcript_text = _render_transcript(conversation_result.turns)
        raw_payload_ref = self._raw_payload_store.store(
            transcript_text.encode("utf-8"), content_type=_TRANSCRIPT_CONTENT_TYPE
        )

        source_document = SourceDocument(
            id=doc_id,
            provenance=Provenance(
                derivation=Derivation.EXTRACTED,
                source_ref=SourceRef(source_document_id=doc_id, region=_TRANSCRIPT_REGION),
                confidence=1.0,
                deriving_agent=A54_AGENT_ID,
                created_at=now,
            ),
            channel=_SOURCE_DOCUMENT_CHANNEL,
            raw_payload_ref=raw_payload_ref,
            document_type=_SOURCE_DOCUMENT_TYPE,
            ingested_at=now,
            original_language="en",
        )
        self._writer.write_node(source_document)

        return CallOutcomeReport(
            call_id=call_id,
            target_provider_id=brief.target_provider_id,
            transcript_source_document_id=doc_id,
            disclosure_given=True,
            claimed_slot=conversation_result.claimed_slot,
            claimed_outcome_summary=conversation_result.claimed_outcome_summary,
            out_of_bounds_encountered=conversation_result.out_of_bounds_encountered,
            requires_human_callback=conversation_result.requires_human_callback,
        )


__all__ = ["VoiceCallTool"]

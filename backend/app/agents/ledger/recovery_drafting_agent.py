"""A30 — Recovery Drafting Agent (spec §10.3E, §15.7).

*Responsibility:* draft cancellations, disputes, claims, and price-
adjustment requests, using a learned per-merchant playbook when the
household has one on file. Consumes an A29 `LeakageFinding` or an A28
`ReconciliationFinding` naming a price/billing issue — reduced by the
caller to a `RecoveryDraftRequest` — and never re-derives the underlying
judgment itself.

*Model tier:* Pro-tier — turning "this is leakage" or "this price rose
silently" into an actual, sendable-quality message that names the exact
ask, cites the exact figures, and follows a vendor's real cancellation
process (when known) is real drafting work, not a template fill.

*Forbidden:* **sending; moving money.** This agent holds no tool of any
kind — no `ToolRegistry`, no send/payment import anywhere in this module.
`RecoveryDraft` (the entire output shape) has no `sent_at`/send-status
field and no field that could carry a payment instruction — dispatching
this draft is Phase 10's Outbound Concierge job, structurally out of this
type's reach.
"""

from __future__ import annotations

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_str
from .types import RecoveryDraft, RecoveryDraftKind, RecoveryDraftRequest

AGENT_ID = AgentId("A30")

logger = structlog.get_logger(__name__)

_OUTCOME_TO_DRAFT_KIND: dict[str, RecoveryDraftKind] = {
    "cancel": "cancellation",
    "price_adjustment_request": "price_adjustment_request",
    "dispute_charge": "dispute_filing",
    "refund_claim": "refund_claim",
}


class RecoveryDraftingAgent:
    """A30 Recovery Drafting. Dependency-injected on a `GeminiClient` only
    — no tool of any kind (see this module's docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def draft(self, request: RecoveryDraftRequest) -> RecoveryDraft:
        """Drafts one recovery message.

        Args:
            request: the finding to draft against, reduced to what this
                agent needs (see `types.RecoveryDraftRequest`).

        Returns:
            A `RecoveryDraft` — draft text only, never dispatched.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape.
        """
        merchant_playbook = request.merchant_playbook or (
            "(no per-merchant playbook on file — use a generic, polite, firm approach)"
        )
        prompt = load_prompt("A30")
        rendered = prompt.text.format(
            finding_kind=request.finding_kind,
            vendor_name=request.vendor_name,
            issue_summary=request.issue_summary,
            desired_outcome=request.desired_outcome,
            merchant_playbook=merchant_playbook,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        target_vendor = require_str(parsed, "target_vendor", agent_id=AGENT_ID)
        ask = require_str(parsed, "ask", agent_id=AGENT_ID)
        message_text = require_str(parsed, "message_text", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)

        draft_kind = _OUTCOME_TO_DRAFT_KIND.get(request.desired_outcome)
        if draft_kind is None:  # pragma: no cover — RecoveryDesiredOutcome is closed; defensive only
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"unmapped desired_outcome {request.desired_outcome!r}",
                raw_text=call_result.text,
            )

        logger.info(
            "agents.ledger.a30.completed",
            vendor=target_vendor,
            draft_kind=draft_kind,
            finding_kind=request.finding_kind,
        )
        return RecoveryDraft(
            target_vendor=target_vendor,
            ask=ask,
            message_text=message_text,
            draft_kind=draft_kind,
            confidence=confidence,
            reasoning=reasoning,
        )


__all__ = ["AGENT_ID", "RecoveryDraftingAgent"]

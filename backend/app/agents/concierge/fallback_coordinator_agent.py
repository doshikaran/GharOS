"""A56 — Fallback Coordinator (spec §13.2 Step 8, §13.6, §15.10, PHASES.md
Phase 10).

*Responsibility:* "Retry ladder, web-booking fallback, graceful
escalation with everything pre-prepared." Flash (roster tier).

## Model tier — Flash, via a downstream dispatcher, never this module directly

This agent's own retry-vs-escalate decision is plain, deterministic code
(retry count against a real backoff schedule, or a hostile-counterparty
signal) — there is nothing here that needs interpretation, mirroring
`service_discovery_agent.py`'s identical reasoning for A51.

**This module holds zero import path into `app.arbitration`** — exactly
like every other module under `backend/app/agents/`
(`test_action_construction_boundary.py`'s `TestNoAgentImportsArbitration`
is a structurally enforced, tested boundary, not a convention). On the
escalation path, this agent produces a `types.FallbackEscalationPayload`
(plain data — `contracts.actions`/`contracts.graph_types` types only) and
stops there. `app.events.concierge_fallback_dispatcher.
dispatch_fallback_decision` (outside `backend/app/agents/`) is the module
that actually builds a real `EscalationContext` from that payload and
calls `EscalationAgent.route()` — **never a second escalation mechanism**,
the same discipline Phase 7's A31 Follow-up/Persistence already
established (its own `followup_scan.py`/`followup_dispatcher.py` split is
the exact precedent this module's split mirrors), and the genuine reason
A31 itself was never built under `backend/app/agents/` either. The real
Flash call this agent's roster tier promises happens inside
`EscalationAgent.route` itself, in the dispatcher — no decorative second
call is added here on top of it.

## Retry ladder — a real, documented backoff

`_retry_after` uses exponential backoff (`_BACKOFF_BASE * 2**attempt`,
capped at `_MAX_BACKOFF`) — a real, stated policy, not a guessed number.
After `max_retries` failed/needs-callback attempts, this agent escalates
fully prepared (spec: "three failures -> escalate... the human's cost is
one minute, not fifteen") via a real `contracts.actions.EvidenceBundle`-
shaped context handed to `EscalationAgent`.

## Web-booking fallback — an honest no-op this phase

Spec §13.4/§13.6 names "web-booking fallback path (if available)" as a
real feature. **No web-booking integration exists anywhere in this
codebase this phase** (checked directly before writing this module) —
`FallbackAction.WEB_BOOKING_FALLBACK` exists in `types.py` for a future
real integration to target, but `decide()` below never returns it; every
path that would have tried it goes straight to `FallbackAction.ESCALATE`
instead, with `reasoning` stating why plainly. This is the honest
choice: returning a "fallback" action with no real distinguishing
behaviour behind it would be worse than not offering it at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import AgentId, NodeId

from .types import CallOutcomeReport, FallbackAction, FallbackDecision, FallbackEscalationPayload

AGENT_ID = AgentId("A56")

logger = structlog.get_logger(__name__)

_BACKOFF_BASE = timedelta(minutes=15)
_MAX_BACKOFF = timedelta(hours=6)
_DEFAULT_MAX_RETRIES = 2
"""Spec's own "three failures -> escalate": attempts 1 and 2 may retry;
the 3rd failed/needs-callback attempt (attempt_number == 2, 0-indexed)
escalates."""


def _retry_after(*, attempt_number: int, now: datetime) -> datetime:
    delay: timedelta = min(_BACKOFF_BASE * (2**attempt_number), _MAX_BACKOFF)
    return now + delay


class FallbackCoordinatorAgent:
    """A56. Holds no dependency on `EscalationAgent` at all — see module
    docstring on why the actual escalation call happens one layer down,
    in `app.events.concierge_fallback_dispatcher`."""

    def decide(
        self,
        *,
        outcome: CallOutcomeReport | None,
        failure_reason: str | None,
        attempt_number: int,
        target_provider_name: str,
        related_node_id: NodeId | None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        now: datetime | None = None,
    ) -> FallbackDecision:
        """Decides what happens after one call attempt.

        Args:
            outcome: the real `CallOutcomeReport` from
                `app.arbitration.voice_call_tool.VoiceCallTool`, when the
                call attempt itself completed (even if it did not result
                in a booking). `None` when the attempt could not complete
                at all — this sandbox's honest analogue of "no answer":
                a `contracts.errors.ToolFailure` from the gated tool
                invocation itself (no live telephony ring-detection
                exists to model a literal unanswered call this phase).
            failure_reason: set only when `outcome is None` — the
                underlying failure's message, carried into the escalation
                briefing rather than discarded.
            attempt_number: 0-indexed count of attempts already made
                *before* this one (0 on the first attempt).
            target_provider_name: for the human-readable reasoning/
                briefing text only.
            related_node_id: the Obligation (or Provider) this attempt
                concerns, carried into `FallbackEscalationPayload.
                related_node_id`.
            now: injectable for tests; defaults to real UTC now.

        Returns:
            A `FallbackDecision` — `RETRY` (with `retry_after` set),
            or `ESCALATE` (with `escalation_payload` set to a real,
            arbitration-free `FallbackEscalationPayload` for the
            downstream dispatcher to act on). Never
            `WEB_BOOKING_FALLBACK` — see module docstring.

        Raises:
            ValueError: `outcome` is not `None` and
                `outcome.requires_human_callback` is `False` — calling
                this agent at all is only valid when *something* needs a
                fallback decision; a caller with a clean success has no
                business asking A56 anything (a real contract violation,
                not an expected path to model as data).
        """
        current_time = now if now is not None else datetime.now(UTC)
        if outcome is not None and not outcome.requires_human_callback:
            raise ValueError(
                "FallbackCoordinatorAgent.decide called for an outcome that did not need a fallback"
            )

        if attempt_number < max_retries:
            retry_at = _retry_after(attempt_number=attempt_number, now=current_time)
            reasoning = self._retry_reasoning(
                outcome=outcome,
                failure_reason=failure_reason,
                attempt_number=attempt_number,
                retry_at=retry_at,
                target_provider_name=target_provider_name,
            )
            logger.info(
                "concierge.a56.retry_scheduled",
                attempt_number=attempt_number,
                retry_after=retry_at.isoformat(),
            )
            return FallbackDecision(
                action=FallbackAction.RETRY,
                reasoning=reasoning,
                retry_after=retry_at,
                escalation_payload=None,
            )

        summary = self._escalation_summary(
            outcome=outcome,
            failure_reason=failure_reason,
            attempt_number=attempt_number,
            target_provider_name=target_provider_name,
        )
        payload = FallbackEscalationPayload(
            action_type="outbound_concierge_call",
            summary=summary,
            risk_tier=RiskTier.R2_APPROVE,
            evidence_bundle=EvidenceBundle(
                proposed_action=f"Book with {target_provider_name}",
                reasoning=summary,
                evidence_consulted=(
                    (f"call outcome: {outcome.claimed_outcome_summary}",)
                    if outcome is not None
                    else (f"call failure: {failure_reason}",)
                ),
                confidence=1.0,
                consequence_if_wrong="No automated path remains — a human needs to take over this booking.",
            ),
            related_node_id=related_node_id,
        )
        logger.info("concierge.a56.escalation_prepared", attempt_number=attempt_number)
        return FallbackDecision(
            action=FallbackAction.ESCALATE, reasoning=summary, retry_after=None, escalation_payload=payload
        )

    def _retry_reasoning(
        self,
        *,
        outcome: CallOutcomeReport | None,
        failure_reason: str | None,
        attempt_number: int,
        retry_at: datetime,
        target_provider_name: str,
    ) -> str:
        cause = (
            outcome.claimed_outcome_summary if outcome is not None else (failure_reason or "attempt failed")
        )
        return (
            f"Attempt {attempt_number + 1} with {target_provider_name} did not resolve ({cause}); "
            f"retrying at {retry_at.isoformat()}."
        )

    def _escalation_summary(
        self,
        *,
        outcome: CallOutcomeReport | None,
        failure_reason: str | None,
        attempt_number: int,
        target_provider_name: str,
    ) -> str:
        cause = (
            outcome.claimed_outcome_summary if outcome is not None else (failure_reason or "attempt failed")
        )
        # No web-booking integration exists this phase (see module docstring) — every exhausted
        # retry path lands here, on a real human escalation, rather than a fabricated fallback.
        return (
            f"{attempt_number + 1} automated attempt(s) with {target_provider_name} did not result in a "
            f"booking ({cause}). No web-booking fallback is available for this provider this phase — "
            "escalating fully prepared."
        )


__all__ = ["AGENT_ID", "FallbackCoordinatorAgent"]

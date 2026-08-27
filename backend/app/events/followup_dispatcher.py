"""A31 — Follow-up / Persistence: turns `followup_scan.FollowUpDecision`s
into real effects.

Two, and only two, real effects — matching A31's own tools-of-none roster
entry (Flash, no tool list at all: it decides and routes, nothing else):

- `"recontact"` -> publishes onto the `followup-triggers` Pub/Sub topic
  (`app.events.publisher.EventPublisher`) — the downstream drafting/
  composing agent (A30 Recovery Drafting or A33 Vendor Relations, neither
  of which this module imports) consumes that event and does the actual
  re-drafting; A31 itself never composes or sends anything.
- `"escalate"` -> calls the real `app.arbitration.escalation_agent.
  EscalationAgent.route()` — reused exactly as PHASES.md's own Phase 7
  instructions require ("reuse it, do not build a second escalation
  mechanism"), with `EscalationReason.STALE_FOLLOWUP` (added this phase,
  `app.arbitration.types`) as the trigger.

`"skip"` dispatches nothing — a not-yet-stale item produces no event, no
escalation, no log noise beyond the scan's own debug trail.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from contracts.actions import RiskTier
from contracts.graph_types import Person

from app.arbitration.escalation_agent import EscalationAgent
from app.arbitration.types import EscalationContext, EscalationReason, EscalationRouting

from .followup_scan import FollowUpDecision
from .publisher import EventPublisher

logger = structlog.get_logger(__name__)

RECONTACT_TOPIC = "followup-triggers"
"""`Settings.pubsub_topic_prefix`-relative topic name — the full topic
(`gharos-followup-triggers` under the default prefix) is created by
`infra/pubsub_topics.sh`, matching this constant (read from here, not
guessed, per that script's own established convention for the heartbeat
topic)."""


class FollowUpDispatcher:
    """Dependency-injected on the real `EventPublisher` and the real
    `EscalationAgent` — this class performs no I/O itself beyond calling
    into those two.
    """

    def __init__(self, *, publisher: EventPublisher, escalation_agent: EscalationAgent) -> None:
        self._publisher = publisher
        self._escalation_agent = escalation_agent

    def dispatch(
        self,
        *,
        decisions: tuple[FollowUpDecision, ...],
        household_people: tuple[Person, ...],
        now: datetime | None = None,
    ) -> tuple[EscalationRouting, ...]:
        """Processes every decision, in order.

        Args:
            decisions: `FollowUpScanner.scan()`'s output for this sweep.
            household_people: passed straight through to `EscalationAgent.
                route()` for any `"escalate"` decisions — see that
                method's own docstring for why this is caller-assembled
                rather than queried here (`GraphReader` has no "list every
                PERSON" primitive).

        Returns:
            One `EscalationRouting` per `"escalate"` decision dispatched,
            in encounter order (empty if nothing needed escalation this
            sweep).
        """
        current_time = now if now is not None else datetime.now(UTC)
        routings: list[EscalationRouting] = []

        for decision in decisions:
            if decision.action == "skip":
                logger.debug(
                    "events.followup_dispatcher.a31.skipped", item_id=decision.item_id, reason=decision.reason
                )
                continue

            if decision.action == "recontact":
                message_id = self._publisher.publish(
                    topic=RECONTACT_TOPIC,
                    payload={
                        "item_id": decision.item_id,
                        "vendor_id": decision.vendor_id or "",
                        "attempt_number": str(decision.attempt_count + 1),
                        "reason": decision.reason,
                        "triggered_at": current_time.isoformat(),
                    },
                )
                logger.info(
                    "events.followup_dispatcher.a31.recontact_triggered",
                    item_id=decision.item_id,
                    message_id=message_id,
                    attempt_number=decision.attempt_count + 1,
                )
                continue

            # decision.action == "escalate"
            escalation = EscalationContext(
                reason=EscalationReason.STALE_FOLLOWUP,
                action_type="followup_recontact",
                summary=(
                    f"Open item {decision.item_id} has had {decision.attempt_count} automated "
                    f"re-contact attempt(s) with no resolution: {decision.reason}"
                ),
                risk_tier=RiskTier.R1_NOTIFY,
                involves_financial=decision.involves_financial,
                involves_signature=False,
                involves_medical=False,
                evidence_bundle=None,
                related_node_id=None,
            )
            routing = self._escalation_agent.route(escalation=escalation, household_people=household_people)
            routings.append(routing)
            logger.info(
                "events.followup_dispatcher.a31.escalated",
                item_id=decision.item_id,
                attempt_count=decision.attempt_count,
                candidate_count=len(routing.candidate_person_ids),
            )

        return tuple(routings)


__all__ = ["RECONTACT_TOPIC", "FollowUpDispatcher"]

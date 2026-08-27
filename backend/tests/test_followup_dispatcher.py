"""Tests for `app.events.followup_dispatcher.FollowUpDispatcher` (A31) —
proves `"recontact"` publishes an event and `"escalate"` reuses the real
`app.arbitration.escalation_agent.EscalationAgent` (PHASES.md Phase 7:
"reuse it, do not build a second escalation mechanism"), never the reverse.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.arbitration.escalation_agent import EscalationAgent
from app.arbitration.types import EscalationReason
from app.events.followup_dispatcher import RECONTACT_TOPIC, FollowUpDispatcher
from app.events.followup_scan import FollowUpDecision
from app.reasoning.gemini_client import GeminiClient
from tests._gemini_fakes import FakeModels, fake_router
from tests.conftest import make_person

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _InMemoryPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []

    def publish(self, *, topic: str, payload: dict[str, str]) -> str:
        self.published.append((topic, payload))
        return f"msg-{len(self.published)}"


def _escalation_agent(text: str = "A household member should review this stale item.") -> EscalationAgent:
    return EscalationAgent(gemini_client=GeminiClient(router=fake_router(FakeModels(texts=[text]))))


class TestRecontactDecisionsPublish:
    def test_recontact_publishes_onto_the_followup_topic(self) -> None:
        publisher = _InMemoryPublisher()
        dispatcher = FollowUpDispatcher(publisher=publisher, escalation_agent=_escalation_agent())
        decision = FollowUpDecision(
            item_id="item-1",
            action="recontact",
            reason="stale",
            attempt_count=1,
            vendor_id="vendor-1",
            involves_financial=True,
        )

        routings = dispatcher.dispatch(decisions=(decision,), household_people=(), now=NOW)

        assert routings == ()
        assert len(publisher.published) == 1
        topic, payload = publisher.published[0]
        assert topic == RECONTACT_TOPIC
        assert payload["item_id"] == "item-1"
        assert payload["attempt_number"] == "2"

    def test_skip_decisions_publish_nothing_and_escalate_nothing(self) -> None:
        publisher = _InMemoryPublisher()
        dispatcher = FollowUpDispatcher(publisher=publisher, escalation_agent=_escalation_agent())
        decision = FollowUpDecision(
            item_id="item-2",
            action="skip",
            reason="not due",
            attempt_count=0,
            vendor_id=None,
            involves_financial=False,
        )

        routings = dispatcher.dispatch(decisions=(decision,), household_people=(), now=NOW)

        assert routings == ()
        assert publisher.published == []


class TestEscalateDecisionsReuseTheRealEscalationAgent:
    def test_escalate_produces_a_routing_via_escalation_agent(self) -> None:
        publisher = _InMemoryPublisher()
        dispatcher = FollowUpDispatcher(publisher=publisher, escalation_agent=_escalation_agent())
        priya = make_person("priya", "Priya", has_bank_access=True)
        decision = FollowUpDecision(
            item_id="item-3",
            action="escalate",
            reason="exhausted attempts",
            attempt_count=3,
            vendor_id="vendor-3",
            involves_financial=True,
        )

        routings = dispatcher.dispatch(decisions=(decision,), household_people=(priya,), now=NOW)

        assert len(routings) == 1
        assert routings[0].reason is EscalationReason.STALE_FOLLOWUP
        assert publisher.published == [], "an escalated item must not also publish a recontact trigger"

    def test_escalation_routes_by_financial_capability_when_involves_financial(self) -> None:
        publisher = _InMemoryPublisher()
        dispatcher = FollowUpDispatcher(publisher=publisher, escalation_agent=_escalation_agent())
        priya = make_person("priya", "Priya", has_bank_access=True)
        arjun = make_person("arjun", "Arjun", has_bank_access=False)
        decision = FollowUpDecision(
            item_id="item-4",
            action="escalate",
            reason="exhausted attempts",
            attempt_count=3,
            vendor_id=None,
            involves_financial=True,
        )

        routings = dispatcher.dispatch(decisions=(decision,), household_people=(priya, arjun), now=NOW)

        assert routings[0].candidate_person_ids == (priya.id,)


class TestMixedBatch:
    def test_each_decision_dispatched_independently(self) -> None:
        publisher = _InMemoryPublisher()
        dispatcher = FollowUpDispatcher(publisher=publisher, escalation_agent=_escalation_agent())
        decisions = (
            FollowUpDecision(
                item_id="skip-1",
                action="skip",
                reason="r",
                attempt_count=0,
                vendor_id=None,
                involves_financial=False,
            ),
            FollowUpDecision(
                item_id="recontact-1",
                action="recontact",
                reason="r",
                attempt_count=0,
                vendor_id="v-1",
                involves_financial=False,
            ),
            FollowUpDecision(
                item_id="escalate-1",
                action="escalate",
                reason="r",
                attempt_count=3,
                vendor_id="v-2",
                involves_financial=True,
            ),
        )

        routings = dispatcher.dispatch(decisions=decisions, household_people=(), now=NOW)

        assert len(publisher.published) == 1
        assert publisher.published[0][1]["item_id"] == "recontact-1"
        assert len(routings) == 1

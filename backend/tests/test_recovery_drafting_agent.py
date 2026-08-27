"""Tests for A30 Recovery Drafting Agent
(`app.agents.ledger.recovery_drafting_agent`).

Unit tests only (fake Gemini, no network). Covers the draft-only contract
(no field on `RecoveryDraft` could ever represent a send) and the
per-merchant-playbook path.
"""

from __future__ import annotations

import json

from app.agents.ledger.recovery_drafting_agent import AGENT_ID, RecoveryDraftingAgent
from app.agents.ledger.types import RecoveryDraft, RecoveryDraftRequest
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(response_obj: dict[str, object]) -> RecoveryDraftingAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return RecoveryDraftingAgent(gemini_client=client)


class TestDraftOnlyOutputShape:
    def test_draft_has_no_send_capable_field(self) -> None:
        """Structural proof mirroring A32's dispute-presentation test: the
        entire `RecoveryDraft` field set has nothing that could represent
        a message having been sent."""
        field_names = set(RecoveryDraft.__dataclass_fields__.keys())
        forbidden_hints = {"sent_at", "sent", "dispatched", "delivery_status", "recipient_reached"}
        assert field_names.isdisjoint(forbidden_hints)

    def test_cancellation_draft_produced(self) -> None:
        agent = _agent(
            {
                "target_vendor": "City Gym Pvt Ltd",
                "ask": "cancel the membership effective immediately",
                "message_text": "Dear City Gym, please cancel membership #4471 effective immediately...",
                "confidence": 0.9,
                "reasoning": "no playbook on file; generic firm cancellation request",
            }
        )
        request = RecoveryDraftRequest(
            finding_kind="leakage",
            vendor_name="City Gym Pvt Ltd",
            issue_summary="unused for 160 days despite a recent price hike to 1500/month",
            desired_outcome="cancel",
        )

        draft = agent.draft(request)

        assert draft.draft_kind == "cancellation"
        assert draft.target_vendor == "City Gym Pvt Ltd"
        assert "cancel" in draft.ask.lower()

    def test_uses_the_given_merchant_playbook(self) -> None:
        agent = _agent(
            {
                "target_vendor": "Sunrise Apartments Society",
                "ask": "roll the maintenance charge back to 2300/month or provide written justification",
                "message_text": "Per society bylaw 4.2, a written notice by email is required...",
                "confidence": 0.8,
                "reasoning": "followed the on-file playbook: written email notice, cite bylaw 4.2",
            }
        )
        request = RecoveryDraftRequest(
            finding_kind="price_change",
            vendor_name="Sunrise Apartments Society",
            issue_summary="maintenance rose from 2300 to 2500 with no notice",
            desired_outcome="price_adjustment_request",
            merchant_playbook="requires a written 30-day notice by email citing society bylaw 4.2",
        )

        draft = agent.draft(request)

        assert draft.draft_kind == "price_adjustment_request"
        assert "bylaw" in draft.message_text.lower()


def test_agent_id_is_a30() -> None:
    assert str(AGENT_ID) == "A30"

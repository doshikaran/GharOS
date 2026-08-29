"""Phase 14.5 (ADR-023) — A2 Intake Router against a *real-shaped* fetched
mailbox message, not a golden-file fixture.

Gate 14.5 / PHASES.md Phase 14.5 E2 item: "confirm A2 routes a real
Gmail/Outlook message end to end (channel `email`), no new classification
branch." The message below is hand-authored to look like what
`GmailConnector` / `OutlookConnector` actually hand the `email_adapter`
after MIME/Graph-JSON parsing: a parent forwarding a school notice to a
family group, so the substantive content sits under a `---------- Forwarded
message ---------` block, a mail-client header block, and one layer of
`>` reply quoting.

Two things are proven:

1. `EmailAdapter.normalize` strips the forwarding/quoting boilerplate
   while keeping every substantive line (dates, the ₹500 fee, the
   nut-free-lunch requirement, the 1:30 PM early dismissal) — no silent
   data loss.
2. That normalized text flows through `IntakeRouter.route` to a correct
   `school_communication` classification, and A2's `route` contains **no
   channel-name branch** — classification stays driven by the
   Document-Type Registry's detection signals, exactly as for every
   other channel (AST check, `test_no_channel_branch_in_a2_route`).
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.email_adapter import EmailAdapter
from app.adapters.ingestion import RawIntakePayload
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake import intake_router as intake_router_module
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

# A representative fetched message body — NOT a checked-in golden fixture.
# This is the `{headers, body}` shape `email_adapter.py` consumes after an
# upstream connector has parsed the MIME / Graph JSON.
_REAL_MAIL_BODY = """\
Hi all,

Forwarding the field-trip note from school for the family group. Someone
please sort out the cash before Wednesday.

Thanks,
Priya

---------- Forwarded message ---------
From: Greenwood International School <office@greenwood.edu.in>
Date: Wed, 27 Aug 2026 at 09:14
Subject: Grade 4 Field Trip - Consent & Payment
To: Priya Sharma <priya.sharma@gmail.com>

> Dear Parents,
>
> The Grade 4 field trip to the Nehru Science Centre is scheduled for
> Friday, 5 September 2026. Kindly note the following:
>
> 1. The signed consent slip is due back by Wednesday, 3 September 2026.
> 2. A contribution of Rs. 500 per child covers transport and entry.
> 3. Children must carry a nut-free packed lunch (school is nut-free).
> 4. Early dismissal at 1:30 PM on the day of the trip.
>
> Please reach out to the class teacher for any queries.
>
> Warm regards,
> Mrs. Anjali Menon
> Grade 4 Coordinator, Greenwood International School
"""

_REAL_MAIL_HEADERS = {
    "from": "Priya Sharma <priya.sharma@gmail.com>",
    "to": "Sharma Family <sharma-family@googlegroups.com>",
    "subject": "Fwd: Grade 4 Field Trip - Consent & Payment",
    "cc": "Rahul Sharma <rahul.sharma@gmail.com>",
}


def _raw_mail() -> RawIntakePayload:
    return RawIntakePayload(
        text=_REAL_MAIL_BODY,
        binary=None,
        media_type="text/plain",
        headers=dict(_REAL_MAIL_HEADERS),
        received_at=datetime(2026, 8, 27, 9, 40, tzinfo=UTC),
    )


def _router_returning(response_obj: dict[str, object]) -> IntakeRouter:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    client = GeminiClient(router=fake_router(FakeModels(texts=[json.dumps(response_obj)])))
    gap_log = RegistryGapLog(InMemoryRegistryGapStore())
    return IntakeRouter(gemini_client=client, registry=registry, gap_log=gap_log)


class TestEmailAdapterKeepsSubstanceDropsBoilerplate:
    def test_normalized_body_drops_forwarding_and_quote_markers(self) -> None:
        normalized = EmailAdapter().normalize(_raw_mail())

        text = normalized.text_content
        assert text is not None
        # forwarding / quoting boilerplate is gone
        assert "Forwarded message" not in text
        assert "From: Greenwood International School" not in text
        assert "Subject: Grade 4 Field Trip" not in text
        assert ">" not in text
        # every substantive line survived
        assert "Nehru Science Centre" in text
        assert "Friday, 5 September 2026" in text
        assert "Wednesday, 3 September 2026" in text
        assert "Rs. 500 per child" in text
        assert "nut-free packed lunch" in text
        assert "Early dismissal at 1:30 PM" in text
        # the outer forwarder's own words are kept too, not just the inner notice
        assert "Forwarding the field-trip note" in text

    def test_channel_and_metadata_are_email_shaped(self) -> None:
        normalized = EmailAdapter().normalize(_raw_mail())
        assert normalized.channel == "email"
        assert normalized.sender == "Priya Sharma <priya.sharma@gmail.com>"
        assert normalized.source_metadata.get("subject") == "Fwd: Grade 4 Field Trip - Consent & Payment"


class TestRealMailRoutesThroughA2:
    def test_forwarded_school_notice_classifies_as_school_communication(self) -> None:
        normalized = EmailAdapter().normalize(_raw_mail())
        router = _router_returning(
            {
                "type_id": "school_communication",
                "type_confidence": 0.88,
                "signals_matched": [
                    "sender_is_school_domain",
                    "field_trip_language",
                    "consent_slip_reference",
                    "early_dismissal_notice",
                ],
                "runner_up_type_id": "permission_slip",
                "runner_up_confidence": 0.31,
                "relevance": "relevant",
                "relevance_reason": "A dated school field-trip notice with a fee and a consent deadline.",
            }
        )

        result = router.route(normalized)

        assert result.resolved is True
        assert result.classified_type_id == "school_communication"
        assert result.registry_gap is None
        assert result.relevance == "relevant"

    def test_low_confidence_real_mail_still_routes_to_triage_not_silently_dropped(self) -> None:
        normalized = EmailAdapter().normalize(_raw_mail())
        router = _router_returning(
            {
                "type_id": "school_communication",
                "type_confidence": 0.20,  # below A2's unresolved floor
                "signals_matched": ["field_trip_language"],
                "runner_up_type_id": None,
                "runner_up_confidence": 0.0,
                "relevance": "relevant",
                "relevance_reason": "Looks school-related but the shape is unclear.",
            }
        )

        result = router.route(normalized)

        assert result.resolved is False
        assert result.registry_gap is not None  # spec §5.4.3 rule 4 — never a silent discard


class TestNoNewChannelBranchInA2:
    """A2 must classify real mail with the *same* registry-signal path it
    uses for every channel — no `if channel == "email"` / `match
    intake.channel` branch was added for Phase 14.5."""

    _CHANNEL_LITERALS = {"email", "gmail", "outlook", "whatsapp", "sms", "chat", "upload", "drive"}

    def _route_ast(self) -> ast.FunctionDef:
        source = inspect.getsource(intake_router_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "route":
                return node
        raise AssertionError("IntakeRouter.route not found")

    def test_no_channel_branch_in_a2_route(self) -> None:
        route = self._route_ast()

        for node in ast.walk(route):
            assert not isinstance(node, ast.Match), (
                "A2's route() gained a `match` statement — Phase 14.5 must not add a channel branch"
            )
            if isinstance(node, ast.Compare):
                literals = {
                    operand.value
                    for operand in [node.left, *node.comparators]
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str)
                }
                offending = literals & self._CHANNEL_LITERALS
                assert not offending, (
                    f"A2's route() compares against a channel-name literal {offending} — classification "
                    "must stay driven by registry detection signals, not the channel"
                )

"""`ChatExportAdapter` against a realistic messy sample: a WhatsApp
"Staff Coordination" group export — code-mixed Hindi/English, a wrapped
multi-line message, a system encryption-notice line, and a casual
commitment embedded in ordinary chat text (spec §5.4.2's own example for
this document type: "I'll pick her up Friday").
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.chat_export_adapter import ChatExportAdapter
from app.adapters.ingestion import IntakeNormalizationError, RawIntakePayload

RECEIVED_AT = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)

_MESSY_WHATSAPP_EXPORT = (
    "22/08/26, 14:00 - Messages and calls are end-to-end encrypted. "
    "No one outside of this chat, not even WhatsApp, can read or listen to them.\n"
    "22/08/26, 14:03 - Priya Sharma: Kal Aarav ko 4 baje school se pick up karna hai,\n"
    " koi jaa sakta hai kya? (need someone to pick him up tomorrow at 4)\n"
    "22/08/26, 14:05 - Rohan Sharma: I'll pick her up Friday, Thursday main busy hoon\n"
    "22/08/26, 14:06 - Meena (Domestic Staff): Didi main bhi ja sakti hoon agar zaroorat ho\n"
)


def _raw(
    *, text: str | None = _MESSY_WHATSAPP_EXPORT, received_at: datetime | None = RECEIVED_AT
) -> RawIntakePayload:
    return RawIntakePayload(
        text=text,
        binary=None,
        media_type="text/plain",
        headers={"group_name": "Staff Coordination"},
        received_at=received_at,
    )


def test_normalizes_messy_whatsapp_export() -> None:
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None

    assert result.channel == "chat_export"
    assert result.sender is None  # multi-party — no single sender
    assert result.source_metadata["group_name"] == "Staff Coordination"
    assert result.source_metadata["message_count"] == "3"  # system line excluded


def test_extracts_distinct_participants_excluding_system_lines() -> None:
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    assert result.participants == ("Meena (Domestic Staff)", "Priya Sharma", "Rohan Sharma")


def test_filters_system_encryption_notice() -> None:
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None
    assert "end-to-end encrypted" not in body


def test_folds_wrapped_continuation_line_into_previous_message() -> None:
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None
    assert "koi jaa sakta hai kya?" in body
    assert "need someone to pick him up tomorrow at 4" in body


def test_preserves_casual_commitment_text_verbatim() -> None:
    """Spec §5.4.2: casual chat commitments ('I'll pick her up Friday')
    are real obligations and must be captured as stated text — this
    adapter's job is to preserve that text intact for A4/A12 downstream,
    never to interpret or drop it."""
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None
    assert "I'll pick her up Friday" in body


def test_uses_last_message_timestamp_when_available() -> None:
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw())
    assert result.received_at == datetime(2026, 8, 22, 14, 6)


def test_raises_on_empty_text() -> None:
    adapter = ChatExportAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text=""))


def test_raises_when_no_line_matches_export_format() -> None:
    adapter = ChatExportAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text="this is just plain text, not an export at all"))


def test_blank_lines_between_messages_are_skipped() -> None:
    text = "22/08/26, 14:03 - Priya Sharma: first message\n\n22/08/26, 14:05 - Rohan Sharma: second message\n"
    adapter = ChatExportAdapter()
    result = adapter.normalize(_raw(text=text))
    assert result.participants == ("Priya Sharma", "Rohan Sharma")


def test_raises_when_no_timestamp_parses_and_no_received_at_fallback() -> None:
    unparseable = "99/99/99, 99:99 - Someone: hello"
    adapter = ChatExportAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text=unparseable, received_at=None))


def test_falls_back_to_received_at_when_no_timestamp_parses() -> None:
    adapter = ChatExportAdapter()
    # A line matching the export shape but with an unparseable date, so
    # the message list is non-empty (format matched) yet carries no valid
    # timestamp — the adapter must fall back to raw.received_at rather
    # than raising.
    unparseable = "99/99/99, 99:99 - Someone: hello"
    result = adapter.normalize(_raw(text=unparseable))
    assert result.received_at == RECEIVED_AT

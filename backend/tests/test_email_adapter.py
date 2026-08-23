"""`EmailAdapter` against a realistic messy sample: a school fee notice
forwarded twice through Gmail, picking up boilerplate and nested quoting
along the way — exactly the shape a real household forwarding chain
produces before this adapter ever sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.email_adapter import EmailAdapter
from app.adapters.ingestion import IntakeNormalizationError, RawIntakePayload

RECEIVED_AT = datetime(2026, 8, 20, 9, 15, tzinfo=UTC)

_MESSY_FORWARDED_BODY = """\
---------- Forwarded message ---------
From: Priya Sharma <priya.sharma@gmail.com>
Date: Thu, Aug 20, 2026 at 9:10 AM
Subject: Fwd: Fwd: Term 2 Fee Payment Reminder
To: Rohan Sharma <rohan.sharma@gmail.com>



On Thu, Aug 20, 2026 at 8:55 AM Greenwood International School <accounts@greenwoodschool.edu> wrote:
> Dear Parent,
>
> This is a reminder that Term 2 fees of INR 45,000 for Aarav Sharma
> (Grade 4B) are due by 30th August 2026. Please pay via the parent
> portal or contact accounts@greenwoodschool.edu for assistance.
>
>> Late payment after the due date attracts a 2% surcharge per week.
>
> Regards,
> Accounts Office


"""

_DEFAULT_HEADERS = {"from": "priya.sharma@gmail.com", "subject": "Fwd: Fwd: Term 2 Fee Payment Reminder"}


def _raw(
    *,
    text: str | None = _MESSY_FORWARDED_BODY,
    headers: dict[str, str] | None = None,
    received_at: datetime | None = RECEIVED_AT,
) -> RawIntakePayload:
    return RawIntakePayload(
        text=text,
        binary=None,
        media_type="text/plain",
        headers=_DEFAULT_HEADERS if headers is None else headers,
        received_at=received_at,
    )


def test_normalizes_messy_forwarded_email_dropping_boilerplate() -> None:
    adapter = EmailAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None

    assert result.channel == "email"
    assert result.sender == "priya.sharma@gmail.com"
    assert result.source_metadata["subject"] == "Fwd: Fwd: Term 2 Fee Payment Reminder"
    assert result.received_at == RECEIVED_AT

    # Forwarding/quoting boilerplate is gone...
    assert "Forwarded message" not in body
    assert "wrote:" not in body
    assert ">" not in body
    # ...but the substantive quoted content survives, de-quoted.
    assert "Term 2 fees of INR 45,000 for Aarav Sharma" in body
    assert "2% surcharge per week" in body


def test_collapses_excess_blank_lines() -> None:
    adapter = EmailAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None
    assert "\n\n\n" not in body


def test_raises_on_missing_body() -> None:
    adapter = EmailAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text=None))


def test_raises_on_missing_sender_header() -> None:
    adapter = EmailAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(headers={"subject": "no from header"}))


def test_raises_on_missing_received_at() -> None:
    adapter = EmailAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(received_at=None))


def test_raises_when_body_is_entirely_boilerplate() -> None:
    adapter = EmailAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text="---------- Forwarded message ---------\nOn Mon wrote:\n"))


def test_raw_payload_ref_is_stable_for_identical_content() -> None:
    adapter = EmailAdapter()
    first = adapter.normalize(_raw())
    second = adapter.normalize(_raw())
    assert first.raw_payload_ref == second.raw_payload_ref


def test_storage_ref_header_takes_precedence_over_content_hash() -> None:
    adapter = EmailAdapter()
    result = adapter.normalize(
        _raw(headers={"from": "a@b.com", "storage_ref": "gs://gharos-raw/emails/msg-1"})
    )
    assert result.raw_payload_ref == "gs://gharos-raw/emails/msg-1"

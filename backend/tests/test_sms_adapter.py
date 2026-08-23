"""`SmsAdapter` against a realistic messy sample: a gateway-templated UPI
debit alert with irregular whitespace padding and an opaque merchant
string — exactly the shape spec §5.4.2 calls out ("PAYTM*XXXXX").
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.ingestion import IntakeNormalizationError, RawIntakePayload
from app.adapters.sms_adapter import SmsAdapter

RECEIVED_AT = datetime(2026, 8, 22, 11, 7, tzinfo=UTC)

_MESSY_UPI_SMS = (
    "Dear Customer,   INR 1,240.00   debited from a/c  XX4821  on 22-Aug-26 "
    "to    PAYTM*XXXXX7712.   UPI Ref  409217563981.  If not you, call 18001234567."
)


def _raw(
    *,
    text: str | None = _MESSY_UPI_SMS,
    headers: dict[str, str] | None = None,
    received_at: datetime | None = RECEIVED_AT,
) -> RawIntakePayload:
    return RawIntakePayload(
        text=text,
        binary=None,
        media_type="text/plain",
        headers={"sender_id": "VM-HDFCBK"} if headers is None else headers,
        received_at=received_at,
    )


def test_normalizes_messy_upi_debit_alert() -> None:
    adapter = SmsAdapter()
    result = adapter.normalize(_raw())
    body = result.text_content
    assert body is not None

    assert result.channel == "sms"
    assert result.sender == "VM-HDFCBK"
    assert result.received_at == RECEIVED_AT
    assert "  " not in body  # whitespace runs collapsed
    assert "PAYTM*XXXXX7712" in body
    assert "409217563981" in body


def test_prefers_sender_id_over_sender_number() -> None:
    adapter = SmsAdapter()
    result = adapter.normalize(_raw(headers={"sender_id": "VM-HDFCBK", "sender_number": "+919876543210"}))
    assert result.sender == "VM-HDFCBK"
    assert result.source_metadata["sender_number"] == "+919876543210"


def test_falls_back_to_sender_number_for_user_forwarded_sms() -> None:
    """A user-forwarded SMS often loses the original alphanumeric sender
    id and arrives with only a forwarding phone number — spec §17's
    documented reality for this channel (no official personal-data API,
    user-forwarded is a first-class path, not a degraded one)."""
    adapter = SmsAdapter()
    result = adapter.normalize(_raw(headers={"sender_number": "+919876543210"}))
    assert result.sender == "+919876543210"


def test_sender_is_none_when_no_identifying_header_present() -> None:
    adapter = SmsAdapter()
    result = adapter.normalize(_raw(headers={}))
    assert result.sender is None


def test_raises_on_empty_body() -> None:
    adapter = SmsAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text=""))


def test_raises_on_whitespace_only_body() -> None:
    adapter = SmsAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(text="    \t   "))


def test_raises_on_missing_received_at() -> None:
    adapter = SmsAdapter()
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(_raw(received_at=None))


def test_raw_payload_ref_stable_for_identical_content() -> None:
    adapter = SmsAdapter()
    first = adapter.normalize(_raw())
    second = adapter.normalize(_raw())
    assert first.raw_payload_ref == second.raw_payload_ref

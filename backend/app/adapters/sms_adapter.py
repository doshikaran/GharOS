"""SMS / UPI alert ingestion adapter (spec §17: "Bank and payment debits |
User-forwarded or Android notification access | **High — no official
personal-data API** | Be transparent").

**Honesty requirement, stated in code per spec §17:** there is no official
API for reading a household member's SMS inbox. This adapter never reads
a device's SMS store directly — it consumes one already-captured message
body (forwarded by the user, or handed over via Android notification-
access tooling that itself is outside this adapter's scope) through
`RawIntakePayload.text`. No live carrier/bank API pull happens here.

Bank and UPI transactional SMS bodies are short, templated, and often
truncated by the sending gateway (spec §5.4.2's own note: merchant
strings are "notoriously opaque" — `PAYTM*XXXXX` is typical, not an
edge case). This adapter's normalization is deliberately light: collapse
whitespace, preserve the message verbatim otherwise. Parsing amount/
direction/counterparty out of that templated text is A3's schema-driven
extraction job (`document_type_specs.py`'s `upi_sms_alert` entry), not
this adapter's — the adapter's contract is "clean text in, clean text
out," never "understand the SMS."
"""

from __future__ import annotations

import re

from app.adapters.ingestion import (
    IntakeNormalizationError,
    NormalizedIntake,
    RawIntakePayload,
    resolve_raw_payload_ref,
)

CHANNEL_NAME = "sms"

_WHITESPACE_RUN_PATTERN = re.compile(r"[ \t]+")


def _normalize_body(body: str) -> str:
    """Collapses runs of horizontal whitespace (common in gateway-templated
    SMS text, which frequently pads fields with multiple spaces) without
    altering line breaks or the substantive content."""
    lines = [_WHITESPACE_RUN_PATTERN.sub(" ", line).strip() for line in body.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class SmsAdapter:
    """`IngestionAdapter` for the SMS/UPI-alert channel. Stateless."""

    channel_name = CHANNEL_NAME

    def normalize(self, raw: RawIntakePayload) -> NormalizedIntake:
        """
        Expects `raw.text` (the SMS body). `raw.headers` may carry
        `"sender_id"` (the bank/gateway alphanumeric sender id, e.g.
        `"VM-HDFCBK"`) and/or `"sender_number"` (a plain phone number for
        user-forwarded messages that don't preserve the original sender
        id) — at least one, when available, becomes `sender`.

        Raises:
            IntakeNormalizationError: `raw.text` is missing/blank.
        """
        if not raw.text or not raw.text.strip():
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="SMS has no body text")

        # No second "entirely whitespace after normalization" check here,
        # unlike `email_adapter._normalize_body`: `_normalize_body` above
        # only collapses whitespace runs, it never drops non-whitespace
        # content the way the email adapter's boilerplate-stripping does —
        # so `raw.text.strip()` being non-empty (checked above) already
        # guarantees `_normalize_body(raw.text)` is non-empty too.
        normalized_body = _normalize_body(raw.text)

        received_at = raw.received_at
        if received_at is None:
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="missing received_at")

        sender = raw.headers.get("sender_id") or raw.headers.get("sender_number")

        source_metadata: dict[str, str] = {}
        for key in ("sender_id", "sender_number"):
            value = raw.headers.get(key)
            if value:
                source_metadata[key] = value

        return NormalizedIntake(
            channel=CHANNEL_NAME,
            raw_payload_ref=resolve_raw_payload_ref(raw, channel=CHANNEL_NAME),
            text_content=normalized_body,
            media_type=raw.media_type or "text/plain",
            received_at=received_at,
            sender=sender,
            participants=(),
            original_language_hint=raw.headers.get("language_hint"),
            source_metadata=source_metadata,
        )


__all__ = ["CHANNEL_NAME", "SmsAdapter"]

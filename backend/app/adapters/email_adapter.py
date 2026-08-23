"""Email ingestion adapter (spec §17: "School, merchants, utilities,
society | Mailbox integration or forwarding address | Low [fragility] |
Most reliable").

Consumes an already-parsed email (headers dict + plain-text body) via
`RawIntakePayload` — the actual mailbox integration or forwarding-address
webhook that turns a raw MIME message into `{"from": ..., "subject": ...}`
headers plus a plain-text body is channel wiring outside Phase 3's scope
(and outside `backend/app/adapters/`'s hexagonal boundary: MIME parsing is
an infrastructure concern the composition root's mail-fetching code
handles before this adapter ever sees the message). This adapter's job is
the *normalization* spec §17 assigns it: strip the noise real household
email accumulates (forwarding boilerplate, quoted reply chains, excess
blank lines) without discarding the substantive content underneath it —
a forwarded school notice's actual text is usually inside three layers of
">" quoting, not in the outermost message.
"""

from __future__ import annotations

import re

from app.adapters.ingestion import (
    IntakeNormalizationError,
    NormalizedIntake,
    RawIntakePayload,
    resolve_raw_payload_ref,
)

CHANNEL_NAME = "email"

_FORWARD_MARKER_PATTERN = re.compile(
    r"^-{2,}\s*forwarded message\s*-{2,}\s*$",
    re.IGNORECASE,
)
"""Matches Gmail/Outlook's standard forwarded-message separator line, e.g.
`---------- Forwarded message ---------`. This line is pure boilerplate —
dropped, never treated as message content."""

_QUOTE_PREFIX_PATTERN = re.compile(r"^\s*>+\s?")
"""Strips leading `>`/`>>`/`> >` reply-quoting markers from a line without
discarding the quoted text itself — a forwarded notice's actual content
routinely lives behind two or three levels of quoting by the time a
household member forwards it onward."""

_ON_WROTE_PATTERN = re.compile(r"^On .{1,120} wrote:\s*$")
"""Matches the standard "On <date>, <name> <email> wrote:" line most mail
clients insert above a quoted reply. Boilerplate — dropped."""

_FORWARD_HEADER_LINE_PATTERN = re.compile(r"^(From|Date|Sent|Subject|To|Cc|Bcc):\s", re.IGNORECASE)
"""Matches the `From:`/`Date:`/`Subject:`/`To:`/... header lines a mail
client inserts directly below its `---------- Forwarded message
---------` separator. Only stripped while `_normalize_body` is inside a
preamble block (immediately after a forward marker or an "On ... wrote:"
line) — see that function — so a line that merely *starts with* one of
these words elsewhere in a message body is never mistaken for a real
mail header."""

_MAX_CONSECUTIVE_BLANK_LINES = 1


def _normalize_body(body: str) -> str:
    """De-quotes, drops forwarding boilerplate (marker lines, "On ...
    wrote:" lines, and the header block a mail client inserts directly
    under a forward marker), and collapses runs of blank lines — see
    module docstring. Never drops non-blank, non-boilerplate content:
    normalization must not become silent data loss.
    """
    kept_lines: list[str] = []
    consecutive_blank = 0
    in_preamble_block = False
    for raw_line in body.splitlines():
        stripped = raw_line.rstrip("\r")

        if _FORWARD_MARKER_PATTERN.match(stripped) or _ON_WROTE_PATTERN.match(stripped):
            in_preamble_block = True
            continue

        if in_preamble_block:
            if stripped.strip() == "":
                in_preamble_block = False  # blank line ends the header block; fall through below
            elif _FORWARD_HEADER_LINE_PATTERN.match(stripped):
                continue  # a From:/Date:/Subject:/To: line inside the block — skip it
            else:
                in_preamble_block = False  # non-header content — block is over; fall through below

        line = _QUOTE_PREFIX_PATTERN.sub("", stripped)
        if line.strip() == "":
            consecutive_blank += 1
            if consecutive_blank > _MAX_CONSECUTIVE_BLANK_LINES:
                continue
        else:
            consecutive_blank = 0
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


class EmailAdapter:
    """`IngestionAdapter` for the email channel. Stateless — safe to
    construct once and reuse, or construct fresh per call; holds no I/O."""

    channel_name = CHANNEL_NAME

    def normalize(self, raw: RawIntakePayload) -> NormalizedIntake:
        """
        Expects `raw.headers` to carry at least `"from"`; `"subject"` and
        `"to"` are preserved into `source_metadata` when present but are
        not required. `raw.text` (the plain-text body) is required — this
        adapter does not accept an email with no text part.

        Raises:
            IntakeNormalizationError: `raw.text` is missing/blank, or
                `raw.headers["from"]` is missing.
        """
        if not raw.text or not raw.text.strip():
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="email has no plain-text body")
        sender = raw.headers.get("from")
        if not sender:
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="missing 'from' header")

        normalized_body = _normalize_body(raw.text)
        if not normalized_body:
            raise IntakeNormalizationError(
                channel=CHANNEL_NAME, reason="email body was entirely forwarding/quoting boilerplate"
            )

        received_at = raw.received_at
        if received_at is None:
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="missing received_at")

        source_metadata: dict[str, str] = {}
        for key in ("subject", "to", "cc"):
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


__all__ = ["CHANNEL_NAME", "EmailAdapter"]

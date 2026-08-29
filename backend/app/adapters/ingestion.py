"""Common shapes for the four Phase 3 ingestion adapters (spec §17): email,
document upload, chat export, SMS.

**This `Protocol` lives here, not in `contracts/`.** `contracts/` is the
CTO-owned, frozen, cross-role shape set (graph types, actions, tools,
repositories, agent I/O) — the shapes every role builds against
independently. `IngestionAdapter` is not that: it is purely an E3-internal
seam between "one channel's messy raw input" and "the normalized shape A2
Intake Router (E2) reads next." No other role imports this module
directly, so freezing it in `contracts/` would buy nothing and would cost
a CTO round-trip every time an adapter's raw-input handling needs to
change shape — exactly the "swappable... ingestion fragility is an
adapter problem, not a core-architecture problem" spec §17 principle this
whole module exists to honour.

Each adapter normalizes; **none of them classify document type** — that
is A2's job (spec §17, PHASES.md Phase 3 E3 column: "these normalize a
channel's raw input into the shape the Intake Router needs, they do NOT
do document-type classification themselves").

**Honesty requirement carried into code, not just docs (spec §17):** SMS
and chat-export (WhatsApp) have no official personal-data API. Both
adapters here consume already-forwarded/exported text — a user forwards
an SMS, or exports/forwards a WhatsApp chat — never a live API pull. See
`sms_adapter.py` and `chat_export_adapter.py` docstrings for the concrete
statement, not just this shared note.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from contracts.ingestion import RawIntakePayload

STORAGE_REF_HEADER = "storage_ref"
"""The `RawIntakePayload.headers` key an upstream channel integration sets
when it has already durably stored the raw payload (E1's source-document
storage, PHASES.md Phase 3 E1 column) before handing input to an adapter.
Named once here so all four adapters read the same key."""

INGESTION_SOURCE_KIND_HEADER = "ingestion_source_kind"
"""The `RawIntakePayload.headers` key the Phase 14.5 ingestion entry point
sets on an *inline* payload (a `direct_upload` multipart part, or a
`drive_picker` fetch) to record which `IngestionSourceKind` it is —
`SourceConnector.fetch_since` output does not need it (the orchestrator
already knows which connector produced each item), but an
`IngestionRequest.inline_payloads` entry carries no other signal of its
kind, and `compute_content_hash` needs the right `source_kind` value.
Absent -> the orchestrator treats the item as `DIRECT_UPLOAD`."""


class IntakeNormalizationError(RuntimeError):
    """Raised when an adapter cannot normalize its raw input into a valid
    `NormalizedIntake` — e.g. a document upload with neither text nor
    binary content, an empty chat export, an SMS with no body. Never
    fabricates a plausible-looking `NormalizedIntake` from unusable input
    (gharos-standards non-negotiable #7's ingestion-layer analogue: a
    failed normalization must surface as a failure, not a best-guess
    success that misleads everything downstream)."""

    def __init__(self, *, channel: str, reason: str) -> None:
        self.channel = channel
        self.reason = reason
        super().__init__(f"{channel} intake normalization failed: {reason}")


# `RawIntakePayload` is RE-HOMED to `contracts.ingestion` as of Phase 14.5
# (ADR-023): the frozen `SourceConnector` protocol returns it and the
# ingestion orchestrator consumes it, so it is now a genuine cross-role
# shape and lives in `contracts/`. This module re-exports the name
# unchanged for its existing callers (the four Phase 3 adapters, which
# import it from here) — `resolve_raw_payload_ref` and `STORAGE_REF_HEADER`
# stay here because they are logic, not shape. See the top-of-module
# `from contracts.ingestion import RawIntakePayload`.


@dataclass(frozen=True, slots=True)
class NormalizedIntake:
    """Channel-agnostic normalized form of one inbound item — what every
    adapter in this package produces, and what A2 Intake Router (E2,
    next round) consumes to classify against
    `DocumentTypeRegistry.known_type_ids()`.

    Maps cleanly onto `contracts.graph_types.SourceDocument`'s own fields
    (`channel`, `raw_payload_ref`, `ingested_at`, `original_language`) —
    A2/A7 (E2's Graph Builder) construct the actual `SourceDocument` node
    from this; adapters never write to the graph themselves (T3 write
    capability belongs to writer agents only, spec §16.1).
    """

    channel: str
    """One of this package's four channel names — `"email"`,
    `"document_upload"`, `"chat_export"`, `"sms"`."""
    raw_payload_ref: str
    """Pointer to where the original raw payload can be re-read from.
    Passed through from `RawIntakePayload.headers["storage_ref"]` when the
    upstream channel integration already uploaded the raw bytes to
    durable storage (E1's "source-document storage with region
    references," PHASES.md Phase 3 E1 column) before calling this
    adapter; adapters never perform that upload themselves (out of E3's
    Phase 3 scope, and out of `backend/app/adapters/`'s hexagonal
    boundary — storage is a persistence concern). Falls back to a stable
    content-derived reference (see each adapter) only when no
    `storage_ref` header is supplied, e.g. in tests."""
    text_content: str | None
    """Normalized plain text, when the channel has any (email body, SMS
    body, chat transcript). `None` for a document-upload item that is a
    pure image/PDF scan with no accompanying text — A3 (multimodal
    extraction, E2) reads the binary directly via `raw_payload_ref` in
    that case."""
    media_type: str
    received_at: datetime
    sender: str | None
    participants: tuple[str, ...]
    """Non-empty only for multi-party channels (chat export); a single
    sender still appears in `sender`, not duplicated here, for the common
    one-sender case."""
    original_language_hint: str | None
    source_metadata: dict[str, str] = field(default_factory=dict)
    """Channel-specific extras worth preserving but not promoted to a
    named field (email subject, SMS short-code/sender-id, upload
    filename) — A2/A3 may read these; the *shape* of this dict is
    intentionally per-channel, documented in each adapter's docstring."""


def resolve_raw_payload_ref(raw: RawIntakePayload, *, channel: str) -> str:
    """Returns `raw.headers[STORAGE_REF_HEADER]` when the upstream channel
    integration already supplied one, otherwise a stable, deterministic
    reference derived from the payload's own content (`sha256` over the
    text and/or binary content, prefixed with `channel`).

    The content-hash fallback exists so adapters remain fully testable and
    usable in local/emulator development without a real storage-upload
    step wired up yet — it is a legitimate stable reference (same content
    in, same ref out), just not one that lets anyone re-fetch the original
    bytes from durable storage the way a real `storage_ref` does. Adapter
    docstrings say this explicitly where relevant.
    """
    storage_ref = raw.headers.get(STORAGE_REF_HEADER)
    if storage_ref:
        return storage_ref
    digest = hashlib.sha256()
    digest.update(channel.encode("utf-8"))
    if raw.text is not None:
        digest.update(raw.text.encode("utf-8"))
    if raw.binary is not None:
        digest.update(raw.binary)
    return f"{channel}:sha256:{digest.hexdigest()}"


class IngestionAdapter(Protocol):
    """The common seam every one of the four Phase 3 adapters implements.

    Structural typing (a `Protocol`, not an ABC) so a concrete adapter
    needs no import from this module to satisfy it in principle — though
    in practice all four here do import it, for the `channel_name`
    convention and so `mypy --strict` checks the method signature.
    """

    channel_name: str

    def normalize(self, raw: RawIntakePayload) -> NormalizedIntake:
        """Normalizes one channel's raw input.

        Raises:
            IntakeNormalizationError: `raw` is missing content this
                channel requires, or is otherwise unparseable.
        """
        ...


__all__ = [
    "INGESTION_SOURCE_KIND_HEADER",
    "STORAGE_REF_HEADER",
    "IngestionAdapter",
    "IntakeNormalizationError",
    "NormalizedIntake",
    "RawIntakePayload",
    "resolve_raw_payload_ref",
]

"""Document upload ingestion adapter (spec §17: "Photographed forms,
notices, registers | Direct upload | Low [fragility] | Best demo surface —
visibly messy").

This is the channel a household member uses to photograph a paper
attendance register, a handwritten society notice, or a receipt with a
phone camera and upload it directly — the messiest input *content*
(handwriting, glare, skew, crumpled paper) but the most reliable input
*mechanism* (no third-party API to go stale, no forwarding-format
guessing). This adapter's job is narrow: validate the upload is a media
type A3 (multimodal extraction, E2) can actually read, and pass the binary
through untouched — image/PDF normalization (deskew, contrast) is A3's
concern, not this adapter's; re-encoding pixels here would be exactly the
kind of extraction-adjacent logic spec §5.4's "extraction is a registry,
not a pipeline branch" design keeps out of the adapter layer.
"""

from __future__ import annotations

from app.adapters.ingestion import (
    IntakeNormalizationError,
    NormalizedIntake,
    RawIntakePayload,
    resolve_raw_payload_ref,
)

CHANNEL_NAME = "document_upload"

SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/webp",
        "application/pdf",
    }
)
"""The media types A3's multimodal extraction (Gemini, spec §21.1) is
documented to handle: photographed forms/registers, scanned notices, and
bill/statement PDFs. An upload outside this set is rejected here rather
than silently passed through to an extraction step that cannot read it."""


class DocumentUploadAdapter:
    """`IngestionAdapter` for the document-upload channel. Stateless."""

    channel_name = CHANNEL_NAME

    def normalize(self, raw: RawIntakePayload) -> NormalizedIntake:
        """
        Expects `raw.binary` (the uploaded file's bytes) and
        `raw.media_type` naming one of `SUPPORTED_MEDIA_TYPES`.
        `raw.headers["filename"]` is preserved into `source_metadata` when
        present.

        A minority of uploads legitimately carry a text sidecar instead of
        (or alongside) binary content — e.g. a household member pastes
        OCR'd text directly rather than uploading a photo — so `raw.text`
        is accepted as a substitute for `raw.binary` when present, but at
        least one of the two is required.

        Raises:
            IntakeNormalizationError: neither `raw.binary` nor `raw.text`
                is present, or `raw.binary` is present with a
                `raw.media_type` outside `SUPPORTED_MEDIA_TYPES`.
        """
        if raw.binary is None and not (raw.text and raw.text.strip()):
            raise IntakeNormalizationError(
                channel=CHANNEL_NAME, reason="upload has neither binary content nor text content"
            )
        if raw.binary is not None and raw.media_type not in SUPPORTED_MEDIA_TYPES:
            allowed = sorted(SUPPORTED_MEDIA_TYPES)
            raise IntakeNormalizationError(
                channel=CHANNEL_NAME,
                reason=f"unsupported media type '{raw.media_type}' — expected one of {allowed}",
            )

        received_at = raw.received_at
        if received_at is None:
            raise IntakeNormalizationError(channel=CHANNEL_NAME, reason="missing received_at")

        source_metadata: dict[str, str] = {}
        filename = raw.headers.get("filename")
        if filename:
            source_metadata["filename"] = filename
        uploaded_by = raw.headers.get("uploaded_by")
        if uploaded_by:
            source_metadata["uploaded_by"] = uploaded_by

        return NormalizedIntake(
            channel=CHANNEL_NAME,
            raw_payload_ref=resolve_raw_payload_ref(raw, channel=CHANNEL_NAME),
            text_content=raw.text.strip() if raw.text else None,
            media_type=raw.media_type,
            received_at=received_at,
            sender=uploaded_by,
            participants=(),
            original_language_hint=raw.headers.get("language_hint"),
            source_metadata=source_metadata,
        )


__all__ = ["CHANNEL_NAME", "SUPPORTED_MEDIA_TYPES", "DocumentUploadAdapter"]

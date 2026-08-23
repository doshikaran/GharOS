"""`DocumentUploadAdapter` against a realistic messy sample: a phone-camera
photo of a handwritten attendance register — a JPEG blob, skewed and
imperfectly lit, uploaded with only a filename and no other metadata
(exactly the minimal wiring a real upload endpoint provides).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.document_upload_adapter import DocumentUploadAdapter
from app.adapters.ingestion import IntakeNormalizationError, RawIntakePayload

RECEIVED_AT = datetime(2026, 8, 21, 18, 42, tzinfo=UTC)

# A minimal-but-real JPEG byte signature (SOI marker + JFIF APP0), not a
# full valid image — enough to exercise "binary content present," which is
# all this adapter's contract cares about (pixel validity is A3's problem).
_FAKE_PHOTO_BYTES = bytes.fromhex("FFD8FFE000104A46494600010100000100010000FFD9")


def test_normalizes_photographed_attendance_register_upload() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text=None,
        binary=_FAKE_PHOTO_BYTES,
        media_type="image/jpeg",
        headers={"filename": "IMG_20260821_184200.jpg", "uploaded_by": "priya.sharma@gmail.com"},
        received_at=RECEIVED_AT,
    )

    result = adapter.normalize(raw)

    assert result.channel == "document_upload"
    assert result.media_type == "image/jpeg"
    assert result.text_content is None
    assert result.sender == "priya.sharma@gmail.com"
    assert result.source_metadata["filename"] == "IMG_20260821_184200.jpg"
    assert result.received_at == RECEIVED_AT
    assert result.raw_payload_ref  # non-empty


def test_accepts_pasted_ocr_text_sidecar_without_binary() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text="  Society Notice: Diwali cleaning charges due 5th Nov  ",
        binary=None,
        media_type="text/plain",
        headers={},
        received_at=RECEIVED_AT,
    )

    result = adapter.normalize(raw)
    assert result.text_content == "Society Notice: Diwali cleaning charges due 5th Nov"


def test_rejects_unsupported_media_type() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text=None,
        binary=b"whatever bytes",
        media_type="application/x-msdownload",
        headers={"filename": "definitely_not_a_form.exe"},
        received_at=RECEIVED_AT,
    )
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(raw)


def test_rejects_upload_with_no_content_at_all() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text=None, binary=None, media_type="image/jpeg", headers={}, received_at=RECEIVED_AT
    )
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(raw)


def test_rejects_missing_received_at() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text=None, binary=_FAKE_PHOTO_BYTES, media_type="image/jpeg", headers={}, received_at=None
    )
    with pytest.raises(IntakeNormalizationError):
        adapter.normalize(raw)


def test_supports_pdf_bill_uploads() -> None:
    adapter = DocumentUploadAdapter()
    raw = RawIntakePayload(
        text=None,
        binary=b"%PDF-1.4 fake-but-present-bytes",
        media_type="application/pdf",
        headers={"filename": "electricity_bill_august.pdf"},
        received_at=RECEIVED_AT,
    )
    result = adapter.normalize(raw)
    assert result.media_type == "application/pdf"

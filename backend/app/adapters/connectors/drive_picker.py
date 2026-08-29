"""Google Drive picker fetch helper (Phase 14.5, ADR-023 §1).

This is **not** a scanning connector — it does not enumerate a Drive. The
frontend Google Picker (`drive.file` scope, no verification) hands the
backend a specific `file_id` the user chose; this helper reads that one
file's metadata + bytes server-side and returns a single
`RawIntakePayload` that joins the same `POST /ingest` wire as a
drag-dropped upload.

Rejects any MIME type outside `document_upload_adapter.SUPPORTED_MEDIA_
TYPES` before downloading bytes — an upload the extraction step cannot
read is refused here, not passed through.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import structlog
from contracts.errors import ConnectorFetchFailed
from contracts.ingestion import EXTERNAL_IDENTITY_HEADER, IngestionSourceKind, RawIntakePayload

from ..document_upload_adapter import SUPPORTED_MEDIA_TYPES
from ..ingestion import INGESTION_SOURCE_KIND_HEADER
from ._http import get_with_backoff

logger = structlog.get_logger(__name__)

_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"
_METADATA_FIELDS = "id,name,mimeType,headRevisionId,size"
_MAX_FILE_BYTES = 25 * 1024 * 1024
_PROVIDER = "google"


class DrivePickerError(RuntimeError):
    """A picked Drive file could not be ingested: it does not exist, is
    not readable with the grant, is an unsupported MIME type, or is too
    large. The `POST /ingest` handler maps this to a `400`/`422` — it is
    a caller/selection problem, distinct from a `SourceConnector`
    precondition failure."""

    def __init__(self, *, file_id: str, reason: str) -> None:
        self.file_id = file_id
        self.reason = reason
        super().__init__(f"drive file {file_id!r}: {reason}")


def fetch_drive_file(
    *,
    file_id: str,
    access_token: str,
    principal: str = "",
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RawIntakePayload:
    """Fetch one user-picked Drive file as a `RawIntakePayload`.

    `EXTERNAL_IDENTITY_HEADER` is `f"{file_id}:{head_revision_id}"` so a
    later edit of the same Drive file (new `headRevisionId`) is correctly
    treated as a new document by `compute_content_hash` (ADR-023 §3).

    Raises:
        DrivePickerError: metadata/download failed, or the MIME type is
            outside `SUPPORTED_MEDIA_TYPES`, or the file exceeds the size
            ceiling.
    """
    metadata = _get_json(
        f"{_FILES_ENDPOINT}/{file_id}",
        {"fields": _METADATA_FIELDS, "supportsAllDrives": "true"},
        access_token=access_token,
        principal=principal,
        file_id=file_id,
        sleep=sleep,
        transport=transport,
    )
    mime_type = str(metadata.get("mimeType") or "")
    if mime_type not in SUPPORTED_MEDIA_TYPES:
        raise DrivePickerError(
            file_id=file_id,
            reason=f"unsupported mimeType {mime_type!r} — expected one of {sorted(SUPPORTED_MEDIA_TYPES)}",
        )
    declared_size = metadata.get("size")
    if isinstance(declared_size, (str, int)) and str(declared_size).isdigit():
        if int(declared_size) > _MAX_FILE_BYTES:
            raise DrivePickerError(
                file_id=file_id, reason=f"file is {declared_size} bytes, over the {_MAX_FILE_BYTES} ceiling"
            )

    head_revision_id = str(metadata.get("headRevisionId") or "unknown")
    filename = str(metadata.get("name") or file_id)

    try:
        response = get_with_backoff(
            f"{_FILES_ENDPOINT}/{file_id}",
            access_token=access_token,
            provider=_PROVIDER,
            principal=principal,
            params={"alt": "media", "supportsAllDrives": "true"},
            transport=transport,
            sleep=sleep,
        )
    except ConnectorFetchFailed as exc:
        raise DrivePickerError(file_id=file_id, reason=exc.reason) from exc

    content = response.content
    if len(content) > _MAX_FILE_BYTES:
        raise DrivePickerError(
            file_id=file_id, reason=f"downloaded {len(content)} bytes, over the {_MAX_FILE_BYTES} ceiling"
        )

    logger.info(
        "connectors.drive_picker.fetched",
        file_id=file_id,
        mime_type=mime_type,
        size_bytes=len(content),
        head_revision_id=head_revision_id,
    )
    return RawIntakePayload(
        text=None,
        binary=content,
        media_type=mime_type,
        headers={
            EXTERNAL_IDENTITY_HEADER: f"{file_id}:{head_revision_id}",
            INGESTION_SOURCE_KIND_HEADER: IngestionSourceKind.DRIVE_PICKER.value,
            "filename": filename,
        },
        received_at=datetime.now(UTC),
    )


def _get_json(
    url: str,
    params: dict[str, str],
    *,
    access_token: str,
    principal: str,
    file_id: str,
    sleep: Callable[[float], None],
    transport: httpx.BaseTransport | None,
) -> dict[str, object]:
    try:
        response = get_with_backoff(
            url,
            access_token=access_token,
            provider=_PROVIDER,
            principal=principal,
            params=params,
            transport=transport,
            sleep=sleep,
        )
    except ConnectorFetchFailed as exc:
        raise DrivePickerError(file_id=file_id, reason=exc.reason) from exc
    try:
        parsed = response.json()
    except ValueError as exc:
        raise DrivePickerError(file_id=file_id, reason=f"metadata response was not JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise DrivePickerError(file_id=file_id, reason="metadata response was not a JSON object")
    return parsed


__all__ = ["DrivePickerError", "fetch_drive_file"]

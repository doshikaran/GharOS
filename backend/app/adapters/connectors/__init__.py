"""Provider connectors for the triggerable ingestion path (Phase 14.5,
ADR-023). Each satisfies `contracts.ingestion.SourceConnector` (Gmail,
Outlook) or is a thin connector-shaped fetch helper (the Drive picker).

They do real HTTP against the provider REST APIs with `httpx`, acquire an
access token in memory via the OAuth client + a Secret-Manager-held
refresh token, and map each item into the `RawIntakePayload` shape the
matching `app.adapters` normalizer already consumes. Nothing here is
importable from `backend/app/agents/` — proven by
`tests/test_safety_invariants.py` (Gate 14.5).
"""

from __future__ import annotations

from .drive_picker import DrivePickerError, fetch_drive_file
from .gmail_connector import GmailConnector
from .outlook_connector import OutlookConnector

__all__ = ["DrivePickerError", "GmailConnector", "OutlookConnector", "fetch_drive_file"]

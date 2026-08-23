"""Structural protocol conformance, enforced by `mypy --strict` — mirrors
`app.graph.conformance`'s pattern (see that module's docstring for the
full rationale: `IngestionAdapter` is a plain `Protocol`, not
`@runtime_checkable`, so these typed factory functions are the structural
equivalent of an `isinstance` check. Each one's return type annotation is
`IngestionAdapter`; if a concrete adapter's `normalize()` signature ever
drifts from the Protocol, `mypy --strict app` fails here. Exercised at
runtime too, in `tests/test_conformance_adapters.py`, to prove
construction succeeds, not just that the annotations line up.
"""

from __future__ import annotations

from app.adapters.chat_export_adapter import ChatExportAdapter
from app.adapters.document_upload_adapter import DocumentUploadAdapter
from app.adapters.email_adapter import EmailAdapter
from app.adapters.ingestion import IngestionAdapter
from app.adapters.sms_adapter import SmsAdapter


def _email_adapter_conforms() -> IngestionAdapter:
    return EmailAdapter()


def _document_upload_adapter_conforms() -> IngestionAdapter:
    return DocumentUploadAdapter()


def _chat_export_adapter_conforms() -> IngestionAdapter:
    return ChatExportAdapter()


def _sms_adapter_conforms() -> IngestionAdapter:
    return SmsAdapter()

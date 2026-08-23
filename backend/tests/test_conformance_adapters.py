"""Exercises `app.adapters.conformance`'s structural-conformance helper
functions at runtime too — `mypy --strict` is their primary enforcement
mechanism (see that module's docstring), but calling them also proves
every constructor actually runs without error, not just that the type
annotations line up. Mirrors `tests/test_conformance.py`'s pattern for
the graph/persistence/audit packages.
"""

from __future__ import annotations

from app.adapters.conformance import (
    _chat_export_adapter_conforms,
    _document_upload_adapter_conforms,
    _email_adapter_conforms,
    _sms_adapter_conforms,
)


def test_all_ingestion_adapter_conformance_factories_construct() -> None:
    assert _email_adapter_conforms() is not None
    assert _document_upload_adapter_conforms() is not None
    assert _chat_export_adapter_conforms() is not None
    assert _sms_adapter_conforms() is not None

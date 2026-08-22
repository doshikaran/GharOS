"""Structural protocol conformance for `AuditLog`, enforced by
`mypy --strict` (see `app.graph.conformance` for the full rationale)."""

from __future__ import annotations

from contracts.repositories import AuditLog
from google.cloud import firestore

from app.audit.audit_log import FirestoreAuditLog


def _audit_log_conforms(client: firestore.Client) -> AuditLog:
    return FirestoreAuditLog(client)

"""Shared codec helpers: `Provenance`, `SourceRef`, `LanguageProfile`,
timezone-aware-datetime enforcement, and small typed-value helpers reused
by every per-node-type codec in `codecs/nodes.py` and `codecs/edges.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Provenance,
    SourceRef,
)


class NaiveDatetimeError(ValueError):
    """Raised when a domain datetime lacks tzinfo. Firestore timestamps are
    always UTC; a naive datetime silently stored would be ambiguous about
    which wall-clock it means, so this is enforced at the write boundary
    rather than left to chance."""

    def __init__(self, *, field: str) -> None:
        self.field = field
        super().__init__(f"datetime field '{field}' is naive (no tzinfo) — must be timezone-aware")


def require_aware(value: datetime, *, field: str) -> datetime:
    """Returns `value` unchanged if timezone-aware; raises `NaiveDatetimeError`
    otherwise. Called on every datetime field at encode time."""
    if value.tzinfo is None:
        raise NaiveDatetimeError(field=field)
    return value


def encode_optional_datetime(value: datetime | None, *, field: str) -> datetime | None:
    return None if value is None else require_aware(value, field=field)


def encode_source_ref(source_ref: SourceRef | None) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return {
        "source_document_id": str(source_ref.source_document_id),
        "region": source_ref.region,
    }


def decode_source_ref(data: dict[str, Any] | None) -> SourceRef | None:
    if data is None:
        return None
    return SourceRef(source_document_id=NodeId(data["source_document_id"]), region=data["region"])


def encode_provenance(provenance: Provenance) -> dict[str, Any]:
    return {
        "derivation": provenance.derivation.value,
        "source_ref": encode_source_ref(provenance.source_ref),
        "confidence": provenance.confidence,
        "deriving_agent": str(provenance.deriving_agent),
        "created_at": require_aware(provenance.created_at, field="provenance.created_at"),
        "superseded_at": encode_optional_datetime(provenance.superseded_at, field="provenance.superseded_at"),
    }


def decode_provenance(data: dict[str, Any]) -> Provenance:
    return Provenance(
        derivation=Derivation(data["derivation"]),
        source_ref=decode_source_ref(data["source_ref"]),
        confidence=data["confidence"],
        deriving_agent=AgentId(data["deriving_agent"]),
        created_at=data["created_at"],
        superseded_at=data.get("superseded_at"),
    )


def encode_language_profile(profile: LanguageProfile) -> dict[str, Any]:
    return {
        "primary_language": profile.primary_language,
        "languages_understood": list(profile.languages_understood),
        "script_preference": profile.script_preference,
        "code_mixing_profile": profile.code_mixing_profile,
        "formality_preference": profile.formality_preference,
        "literacy_mode": profile.literacy_mode.value,
    }


def decode_language_profile(data: dict[str, Any]) -> LanguageProfile:
    return LanguageProfile(
        primary_language=data["primary_language"],
        languages_understood=tuple(data["languages_understood"]),
        script_preference=data["script_preference"],
        code_mixing_profile=data.get("code_mixing_profile"),
        formality_preference=data.get("formality_preference"),
        literacy_mode=LiteracyMode(data["literacy_mode"]),
    )

"""Two small T3 tools backing the voice subsystem's settings surfaces
(PHASES.md Phase 13 item 5): voiceprint enrollment (A66's own enrollment
path, spec §15.11) and per-person `LanguageProfile` updates (E4's
settings screen, spec §14.3). Both mirror ADR-019 Decision 5's "no new
persistence mechanism needed" precedent exactly — built entirely on the
existing generic `GraphWriter.supersede_node`, plus (for enrollment) the
existing generic `RawPayloadStore` every other channel already uses
(ADR-020's own instruction: "the same ingestion.py/raw_payload_store
path"). Neither tool introduces a new write path, a new node type, or a
new edge type.

T3 is not a gated tier (`contracts.tools.GATED_TIERS` is T4/T5/T6 only),
so — unlike a T4/T5/T6 tool — both classes here are registrable from
anywhere `PermissionTier.T3_INTERNAL_WRITE` is a writer agent's permitted
tier, matching `app.tools.graph_write_tool.GraphWriteTool`'s own
precedent exactly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from contracts.actions import ActionResult
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    Provenance,
)
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import IdempotentTool, PermissionTier

from app.persistence.raw_payload_store import RawPayloadStore

_DEFAULT_VOICEPRINT_CONTENT_TYPE = "audio/L16"


class PersonNotFound(Exception):
    """Raised by either tool below when `person_id` does not resolve to a
    current `contracts.graph_types.Person` node — a caller error (a stale
    or malformed id), never a graph-integrity concern. Mirrors
    `app.tools.booking_write_tool.BookingNotVerified`'s established
    precedent: a tool-local typed error, not a `contracts.errors` member
    (the frozen contract deliberately leaves tool-effect error taxonomies
    to each owning package)."""

    def __init__(self, *, person_id: str) -> None:
        self.person_id = person_id
        super().__init__(f"no current Person node found for id {person_id!r}")


def _require_person(graph_reader: GraphReader, person_id: str) -> Person:
    current = graph_reader.get_node(NodeId(person_id))
    if not isinstance(current, Person):
        raise PersonNotFound(person_id=person_id)
    return current


class VoiceprintEnrollmentTool(IdempotentTool):
    """T3. Stores a household member's reference voice clip via
    `RawPayloadStore.store` (the exact same durable-storage path every
    other channel's raw payload already goes through) and sets `Person.
    voiceprint_ref` to the resulting ref via `GraphWriter.supersede_node`.
    """

    def __init__(
        self,
        *,
        graph_reader: GraphReader,
        graph_writer: GraphWriter,
        raw_payload_store: RawPayloadStore,
        idempotency_store: IdempotencyStore,
        name: str = "voiceprint_enrollment",
    ) -> None:
        self.name = name
        self.tier: PermissionTier = PermissionTier.T3_INTERNAL_WRITE
        self._reader = graph_reader
        self._writer = graph_writer
        self._raw_payload_store = raw_payload_store
        self._idempotency_store = idempotency_store

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Enrolls one reference clip for a household member.

        Args (via kwargs):
            person_id: the `Person` node id (`str`) to enroll.
            audio: the real reference clip bytes.
            mime_type: `audio`'s real MIME type (defaults to
                `"audio/L16"` — raw PCM, matching the WebSocket wire
                format — if omitted).

        Returns:
            `ActionResult.success({"person_id": ..., "voiceprint_ref": ...})`.
            A replay with the same `idempotency_key` returns the original
            call's `voiceprint_ref` without writing again.

        Raises:
            PersonNotFound: `person_id` does not resolve to a current
                `Person` node.
            contracts.errors.ToolFailure: `person_id`/`audio` missing or
                malformed, or the underlying write failed.
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(cached_result_ref)

        person_id = kwargs.get("person_id")
        audio = kwargs.get("audio")
        mime_type = kwargs.get("mime_type", _DEFAULT_VOICEPRINT_CONTENT_TYPE)
        if not isinstance(person_id, str) or not person_id:
            raise ToolFailure(tool_name=self.name, reason="'person_id' (str) is required", retryable=False)
        if not isinstance(audio, bytes) or not audio:
            raise ToolFailure(
                tool_name=self.name, reason="'audio' (non-empty bytes) is required", retryable=False
            )
        if not isinstance(mime_type, str):
            raise ToolFailure(tool_name=self.name, reason="'mime_type' must be a string", retryable=False)

        current = _require_person(self._reader, person_id)
        raw_payload_ref = self._raw_payload_store.store(audio, content_type=mime_type)

        updated = replace(
            current,
            voiceprint_ref=raw_payload_ref,
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=1.0,
                deriving_agent=AgentId("A66"),
                created_at=datetime.now(UTC),
            ),
        )
        try:
            self._writer.supersede_node(NodeId(person_id), updated)
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, see graph_read_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        result = {"person_id": person_id, "voiceprint_ref": raw_payload_ref}
        self._idempotency_store.record_result(idempotency_key, raw_payload_ref)
        return ActionResult.success(result)


_LANGUAGE_PROFILE_FIELDS = (
    "primary_language",
    "languages_understood",
    "script_preference",
    "code_mixing_profile",
    "formality_preference",
    "literacy_mode",
)


class LanguageProfileTool(IdempotentTool):
    """T3. Reads a `Person`'s current `LanguageProfile`, merges in only
    the fields the caller actually supplied (a partial update — every
    field omitted keeps its current value), and writes the resulting
    `Person` via `GraphWriter.supersede_node`. No new persistence
    mechanism — the exact same pattern `VoiceprintEnrollmentTool` above
    uses for the same reason (ADR-019 Decision 5's precedent)."""

    def __init__(
        self,
        *,
        graph_reader: GraphReader,
        graph_writer: GraphWriter,
        idempotency_store: IdempotencyStore,
        name: str = "language_profile_writer",
    ) -> None:
        self.name = name
        self.tier: PermissionTier = PermissionTier.T3_INTERNAL_WRITE
        self._reader = graph_reader
        self._writer = graph_writer
        self._idempotency_store = idempotency_store

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Applies a partial `LanguageProfile` update.

        Args (via kwargs):
            person_id: the `Person` node id (`str`) to update.
            updates: a `dict[str, object]` containing only the
                `LanguageProfile` fields to change (any of
                `_LANGUAGE_PROFILE_FIELDS`); `languages_understood`, if
                present, must be a list/tuple of strings.

        Returns:
            `ActionResult.success(person_id)` — a replay with the same
            `idempotency_key` is a no-op returning the same id, per spec
            §19.1.

        Raises:
            PersonNotFound: `person_id` does not resolve to a current
                `Person` node.
            contracts.errors.ToolFailure: `person_id`/`updates` missing or
                malformed, or the underlying write failed.
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(cached_result_ref)

        person_id = kwargs.get("person_id")
        updates = kwargs.get("updates")
        if not isinstance(person_id, str) or not person_id:
            raise ToolFailure(tool_name=self.name, reason="'person_id' (str) is required", retryable=False)
        if not isinstance(updates, dict):
            raise ToolFailure(tool_name=self.name, reason="'updates' (dict) is required", retryable=False)

        current = _require_person(self._reader, person_id)
        new_profile = self._merged_profile(current.language_profile, updates)

        updated = replace(
            current,
            language_profile=new_profile,
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=1.0,
                deriving_agent=AgentId("A62"),
                created_at=datetime.now(UTC),
            ),
        )
        try:
            self._writer.supersede_node(NodeId(person_id), updated)
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, see graph_read_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        self._idempotency_store.record_result(idempotency_key, person_id)
        return ActionResult.success(person_id)

    def _merged_profile(self, current: LanguageProfile, updates: dict[object, object]) -> LanguageProfile:
        unknown_keys = set(updates) - set(_LANGUAGE_PROFILE_FIELDS)
        if unknown_keys:
            raise ToolFailure(
                tool_name=self.name,
                reason=f"unknown language_profile field(s): {sorted(str(k) for k in unknown_keys)}",
                retryable=False,
            )

        languages_understood = current.languages_understood
        if "languages_understood" in updates:
            raw = updates["languages_understood"]
            if not isinstance(raw, list | tuple) or not all(isinstance(item, str) for item in raw):
                raise ToolFailure(
                    tool_name=self.name,
                    reason="'languages_understood' must be a list of strings",
                    retryable=False,
                )
            languages_understood = tuple(raw)

        literacy_mode = current.literacy_mode
        if "literacy_mode" in updates:
            raw_mode = updates["literacy_mode"]
            if not isinstance(raw_mode, str):
                raise ToolFailure(
                    tool_name=self.name, reason="'literacy_mode' must be a string", retryable=False
                )
            try:
                literacy_mode = LiteracyMode(raw_mode)
            except ValueError as exc:
                raise ToolFailure(
                    tool_name=self.name,
                    reason=f"'literacy_mode' {raw_mode!r} is not a valid LiteracyMode",
                    retryable=False,
                ) from exc

        def _str_or_current(key: str, current_value: str) -> str:
            value = updates.get(key, current_value)
            if not isinstance(value, str):
                raise ToolFailure(tool_name=self.name, reason=f"{key!r} must be a string", retryable=False)
            return value

        def _optional_str_or_current(key: str, current_value: str | None) -> str | None:
            if key not in updates:
                return current_value
            value = updates[key]
            if value is not None and not isinstance(value, str):
                raise ToolFailure(
                    tool_name=self.name, reason=f"{key!r} must be a string or null", retryable=False
                )
            return value

        return LanguageProfile(
            primary_language=_str_or_current("primary_language", current.primary_language),
            languages_understood=languages_understood,
            script_preference=_str_or_current("script_preference", current.script_preference),
            code_mixing_profile=_optional_str_or_current("code_mixing_profile", current.code_mixing_profile),
            formality_preference=_optional_str_or_current(
                "formality_preference", current.formality_preference
            ),
            literacy_mode=literacy_mode,
        )


__all__ = ["LanguageProfileTool", "PersonNotFound", "VoiceprintEnrollmentTool"]

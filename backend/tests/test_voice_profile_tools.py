"""Tests for `app.tools.voice_profile_tools` — the two T3 tools backing
voiceprint enrollment and per-person language-profile updates (PHASES.md
Phase 13 item 5, ADR-019 Decision 5's "no new persistence mechanism"
precedent).

Unit tests only — `_fake_graph_reader.FakeGraphReader` / `_fake_graph_
writer.FakeGraphWriter` / `_fake_idempotency_store.InMemoryIdempotency
Store` / `_fake_raw_payload_store.FakeRawPayloadStore` prove *what* each
tool writes without a Firestore emulator, mirroring `test_staff_payroll_
agent.py`'s established precedent for the same fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)

from app.tools.voice_profile_tools import LanguageProfileTool, PersonNotFound, VoiceprintEnrollmentTool

from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._fake_raw_payload_store import FakeRawPayloadStore


def _person(person_id: str = "person-1") -> Person:
    return Person(
        id=NodeId(person_id),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
            confidence=0.9,
            deriving_agent=AgentId("A0"),
            created_at=datetime.now(UTC),
        ),
        display_name="Priya",
        aliases=(),
        role=PersonRole.ADULT,
        can_drive=True,
        can_sign=True,
        has_bank_access=True,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=LanguageProfile(
            primary_language="hi",
            languages_understood=("hi", "en"),
            script_preference="devanagari",
            code_mixing_profile="hi-en",
            formality_preference="informal",
            literacy_mode=LiteracyMode.BOTH,
        ),
    )


def _reader(*people: Person) -> FakeGraphReader:
    return FakeGraphReader(nodes_by_id={str(person.id): person for person in people})


class TestVoiceprintEnrollmentTool:
    def test_enrolls_a_reference_clip_and_sets_voiceprint_ref(self) -> None:
        reader = _reader(_person())
        writer = FakeGraphWriter()
        payload_store = FakeRawPayloadStore()
        tool = VoiceprintEnrollmentTool(
            graph_reader=reader,
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
        )

        result = tool.invoke_idempotent(
            "key-1", person_id="person-1", audio=b"\x00\x01\x02", mime_type="audio/L16"
        )

        assert result.ok is True
        assert isinstance(result.value, dict)
        assert result.value["person_id"] == "person-1"
        updated = writer.nodes[NodeId("person-1")]
        assert isinstance(updated, Person)
        assert updated.voiceprint_ref == result.value["voiceprint_ref"]
        assert updated.voiceprint_ref is not None
        assert payload_store.retrieve(updated.voiceprint_ref) == b"\x00\x01\x02"

    def test_replay_with_same_key_does_not_write_again(self) -> None:
        reader = _reader(_person())
        writer = FakeGraphWriter()
        idempotency_store = InMemoryIdempotencyStore()
        tool = VoiceprintEnrollmentTool(
            graph_reader=reader,
            graph_writer=writer,
            raw_payload_store=FakeRawPayloadStore(),
            idempotency_store=idempotency_store,
        )
        tool.invoke_idempotent("key-1", person_id="person-1", audio=b"\x00\x01", mime_type="audio/L16")
        tool.invoke_idempotent("key-1", person_id="person-1", audio=b"\x00\x01", mime_type="audio/L16")

        assert writer.write_node_calls == 0  # supersede_node only, never a plain write_node

    def test_unknown_person_raises_person_not_found(self) -> None:
        tool = VoiceprintEnrollmentTool(
            graph_reader=_reader(),
            graph_writer=FakeGraphWriter(),
            raw_payload_store=FakeRawPayloadStore(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(PersonNotFound):
            tool.invoke_idempotent(
                "key-1", person_id="does-not-exist", audio=b"\x00\x01", mime_type="audio/L16"
            )

    def test_missing_audio_raises_tool_failure(self) -> None:
        tool = VoiceprintEnrollmentTool(
            graph_reader=_reader(_person()),
            graph_writer=FakeGraphWriter(),
            raw_payload_store=FakeRawPayloadStore(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-1", person_id="person-1")


class TestLanguageProfileTool:
    def test_partial_update_keeps_unspecified_fields(self) -> None:
        reader = _reader(_person())
        writer = FakeGraphWriter()
        tool = LanguageProfileTool(
            graph_reader=reader, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
        )

        result = tool.invoke_idempotent("key-1", person_id="person-1", updates={"primary_language": "en"})

        assert result.ok is True
        updated = writer.nodes[NodeId("person-1")]
        assert isinstance(updated, Person)
        assert updated.language_profile.primary_language == "en"
        # Everything else is unchanged from the original profile.
        assert updated.language_profile.script_preference == "devanagari"
        assert updated.language_profile.languages_understood == ("hi", "en")

    def test_updates_languages_understood_and_literacy_mode(self) -> None:
        reader = _reader(_person())
        writer = FakeGraphWriter()
        tool = LanguageProfileTool(
            graph_reader=reader, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
        )

        tool.invoke_idempotent(
            "key-1",
            person_id="person-1",
            updates={"languages_understood": ["hi", "en", "mr"], "literacy_mode": "voice_only"},
        )

        updated = writer.nodes[NodeId("person-1")]
        assert isinstance(updated, Person)
        assert updated.language_profile.languages_understood == ("hi", "en", "mr")
        assert updated.language_profile.literacy_mode is LiteracyMode.VOICE_ONLY

    def test_unknown_field_raises_tool_failure(self) -> None:
        tool = LanguageProfileTool(
            graph_reader=_reader(_person()),
            graph_writer=FakeGraphWriter(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-1", person_id="person-1", updates={"not_a_real_field": "x"})

    def test_invalid_literacy_mode_raises_tool_failure(self) -> None:
        tool = LanguageProfileTool(
            graph_reader=_reader(_person()),
            graph_writer=FakeGraphWriter(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent(
                "key-1", person_id="person-1", updates={"literacy_mode": "not-a-real-mode"}
            )

    def test_unknown_person_raises_person_not_found(self) -> None:
        tool = LanguageProfileTool(
            graph_reader=_reader(),
            graph_writer=FakeGraphWriter(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(PersonNotFound):
            tool.invoke_idempotent("key-1", person_id="does-not-exist", updates={"primary_language": "en"})

    def test_replay_with_same_key_does_not_write_again(self) -> None:
        reader = _reader(_person())
        writer = FakeGraphWriter()
        idempotency_store = InMemoryIdempotencyStore()
        tool = LanguageProfileTool(
            graph_reader=reader, graph_writer=writer, idempotency_store=idempotency_store
        )
        tool.invoke_idempotent("key-1", person_id="person-1", updates={"primary_language": "en"})
        tool.invoke_idempotent("key-1", person_id="person-1", updates={"primary_language": "en"})
        assert idempotency_store.reserve_calls == 2
        assert idempotency_store.record_calls == 1


__all__: list[str] = []

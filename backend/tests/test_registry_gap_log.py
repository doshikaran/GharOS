"""`RegistryGapLog` — the queryable "registry gap" mechanism spec §5.4.3
rule 4 requires ("log it as a registry gap — this is how the registry
grows"). Proves the full real flow: `DocumentTypeRegistry.resolve()` on an
unknown type raises `contracts.errors.RegistryGap`, the caller catches it
and records it via `record_registry_gap`, and the record is genuinely
retrievable afterward via `list_gaps()` — not merely printed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.errors import RegistryGap

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.registry_gap_log import (
    InMemoryRegistryGapStore,
    RegistryGapLog,
    record_registry_gap,
)

FIXED_NOW = datetime(2026, 8, 23, 9, 30, tzinfo=UTC)


def test_record_appends_and_logs_a_retrievable_record() -> None:
    store = InMemoryRegistryGapStore()
    gap_log = RegistryGapLog(store, clock=lambda: FIXED_NOW)

    record = gap_log.record(
        type_id_attempted="carrier_pigeon_notice",
        detection_summary="no registered strategy for 'carrier_pigeon_notice'",
        channel="document_upload",
        detection_signals_seen=("wax_seal",),
        source_document_ref="doc-42",
    )

    assert record.occurred_at == FIXED_NOW
    retrieved = gap_log.list_gaps()
    assert retrieved == (record,)
    assert retrieved[0].type_id_attempted == "carrier_pigeon_notice"
    assert retrieved[0].channel == "document_upload"


def test_list_gaps_accumulates_across_multiple_records() -> None:
    store = InMemoryRegistryGapStore()
    gap_log = RegistryGapLog(store, clock=lambda: FIXED_NOW)

    gap_log.record(type_id_attempted="a", detection_summary="gap a", channel="email")
    gap_log.record(type_id_attempted="b", detection_summary="gap b", channel="sms")

    gaps = gap_log.list_gaps()
    assert len(gaps) == 2
    assert {gap.type_id_attempted for gap in gaps} == {"a", "b"}


def test_record_never_raises_even_with_empty_optional_fields() -> None:
    store = InMemoryRegistryGapStore()
    gap_log = RegistryGapLog(store, clock=lambda: FIXED_NOW)

    record = gap_log.record(type_id_attempted=None, detection_summary="totally unclassifiable", channel="sms")

    assert record.type_id_attempted is None
    assert record.detection_signals_seen == ()
    assert record.source_document_ref is None


def test_end_to_end_unknown_type_resolution_logs_a_registry_gap() -> None:
    """The real flow: A2 Intake Router (E2, next round) calls
    `registry.resolve(classified_type_id)`, catches `RegistryGap`, and
    records it — this is that flow, exercised here without E2's code."""
    registry = DocumentTypeRegistry()
    store = InMemoryRegistryGapStore()
    gap_log = RegistryGapLog(store, clock=lambda: FIXED_NOW)

    assert gap_log.list_gaps() == ()

    with pytest.raises(RegistryGap) as exc_info:
        try:
            registry.resolve("handwritten_pet_adoption_form")
        except RegistryGap as gap_error:
            record_registry_gap(
                gap_log,
                gap_error,
                channel="document_upload",
                type_id_attempted="handwritten_pet_adoption_form",
                detection_signals_seen=("signature_block",),
                source_document_ref="doc-99",
            )
            raise

    assert "handwritten_pet_adoption_form" in str(exc_info.value)

    gaps = gap_log.list_gaps()
    assert len(gaps) == 1
    assert gaps[0].type_id_attempted == "handwritten_pet_adoption_form"
    assert gaps[0].channel == "document_upload"
    assert gaps[0].source_document_ref == "doc-99"
    assert "handwritten_pet_adoption_form" in gaps[0].detection_summary


def test_as_log_fields_is_json_primitive_shaped() -> None:
    store = InMemoryRegistryGapStore()
    gap_log = RegistryGapLog(store, clock=lambda: FIXED_NOW)
    record = gap_log.record(
        type_id_attempted="x",
        detection_summary="summary",
        channel="chat_export",
        detection_signals_seen=("a", "b"),
    )

    fields = record.as_log_fields()
    assert fields["type_id_attempted"] == "x"
    assert fields["detection_signals_seen"] == "a,b"
    assert fields["occurred_at"] == FIXED_NOW.isoformat()

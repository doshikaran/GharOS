"""`DocumentTypeRegistry` — register/resolve round-trip, duplicate/mismatch
guards, unknown-type behaviour, `known_type_ids()`. No Firestore/network
I/O — a fresh `DocumentTypeRegistry()` per test proves the "no
module-level singleton" testability requirement directly.
"""

from __future__ import annotations

import pytest
from contracts.errors import RegistryGap
from contracts.graph_types import AgentId, ExtractedField, GraphMappingResult, NodeId

from app.adapters.document_registry import DocumentTypeRegistry, DuplicateRegistration, TypeIdMismatch
from app.adapters.document_type_ids import RECEIPT, UTILITY_BILL
from app.adapters.document_type_specs import DOCUMENT_TYPE_SPECS_BY_ID


class _StubExtractionStrategy:
    """Minimal `ExtractionStrategy` conformance for registry tests — the
    registry must work with *any* conforming strategy without caring what
    it does, so this stub never needs real mapping logic (E2 owns real
    strategies in the following round)."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        return GraphMappingResult(nodes=(), edges=())


def test_register_then_resolve_round_trips() -> None:
    registry = DocumentTypeRegistry()
    spec = DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT]
    strategy = _StubExtractionStrategy()

    registry.register(RECEIPT, spec, strategy)
    resolved_spec, resolved_strategy = registry.resolve(RECEIPT)

    assert resolved_spec is spec
    assert resolved_strategy is strategy


def test_fresh_registry_per_instance_has_no_shared_state() -> None:
    """Two independently constructed registries must not see each other's
    registrations — proves there is no module-level singleton backing
    this class."""
    registry_a = DocumentTypeRegistry()
    registry_b = DocumentTypeRegistry()
    spec = DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT]

    registry_a.register(RECEIPT, spec, _StubExtractionStrategy())

    assert registry_a.has_type(RECEIPT)
    assert not registry_b.has_type(RECEIPT)
    assert len(registry_b) == 0


def test_register_rejects_type_id_spec_mismatch() -> None:
    registry = DocumentTypeRegistry()
    spec = DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT]

    with pytest.raises(TypeIdMismatch):
        registry.register(UTILITY_BILL, spec, _StubExtractionStrategy())


def test_register_rejects_duplicate_type_id() -> None:
    registry = DocumentTypeRegistry()
    spec = DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT]
    registry.register(RECEIPT, spec, _StubExtractionStrategy())

    with pytest.raises(DuplicateRegistration):
        registry.register(RECEIPT, spec, _StubExtractionStrategy())


def test_resolve_unknown_type_raises_registry_gap() -> None:
    registry = DocumentTypeRegistry()

    with pytest.raises(RegistryGap) as exc_info:
        registry.resolve("carrier_pigeon_notice")

    assert "carrier_pigeon_notice" in str(exc_info.value)


def test_known_type_ids_reflects_registrations_sorted() -> None:
    registry = DocumentTypeRegistry()
    registry.register(UTILITY_BILL, DOCUMENT_TYPE_SPECS_BY_ID[UTILITY_BILL], _StubExtractionStrategy())
    registry.register(RECEIPT, DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT], _StubExtractionStrategy())

    assert registry.known_type_ids() == (RECEIPT, UTILITY_BILL)


def test_has_type_false_before_registration_true_after() -> None:
    registry = DocumentTypeRegistry()
    assert registry.has_type(RECEIPT) is False

    registry.register(RECEIPT, DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT], _StubExtractionStrategy())
    assert registry.has_type(RECEIPT) is True


def test_len_reports_registration_count() -> None:
    registry = DocumentTypeRegistry()
    assert len(registry) == 0
    registry.register(RECEIPT, DOCUMENT_TYPE_SPECS_BY_ID[RECEIPT], _StubExtractionStrategy())
    assert len(registry) == 1


def test_adding_a_new_type_requires_no_pipeline_modification() -> None:
    """PHASES.md Phase 3 test requirement: 'adding a new type requires no
    pipeline modification.' Demonstrated here by registering a completely
    novel, made-up type_id with no special-casing anywhere in
    `DocumentTypeRegistry` — the class has no branch on any specific
    type_id string, so a fifteenth type is exactly as supported as the
    fourteen canonical ones."""
    registry = DocumentTypeRegistry()
    from contracts.graph_types import DocumentTypeSpec, FieldSchema

    novel_spec = DocumentTypeSpec(
        type_id="carrier_pigeon_notice",
        detection_signals=("wax_seal", "leg_band_reference"),
        field_schema=(
            FieldSchema(name="sender_loft", field_type="string", required=True, confidence_floor=0.6),
        ),
        target_node_types=("OBLIGATION",),
        target_edge_types=(),
        downstream_subsystems=("consequence_engine",),
        verification_duties=(),
    )
    registry.register("carrier_pigeon_notice", novel_spec, _StubExtractionStrategy())

    resolved_spec, _ = registry.resolve("carrier_pigeon_notice")
    assert resolved_spec is novel_spec
    assert "carrier_pigeon_notice" in registry.known_type_ids()

"""Gate 3 checklist item: "Adding a new type requires no pipeline
modification."

Defines a fictional **fifteenth** document type entirely inline in this
test file — a `DocumentTypeSpec` + one `ExtractionStrategy` class — and
routes it through the exact same A2 -> A3 -> strategy pipeline code every
one of the real fourteen types uses, with zero changes to
`intake_router.py`, `document_extraction.py`, or `DocumentTypeRegistry`.
If this test needs to touch any of those three files to pass, ADR-008's
open-registry claim is false.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    DocumentTypeSpec,
    ExtractedField,
    FieldSchema,
    GraphMappingResult,
    NodeId,
    Provenance,
    SourceRef,
    Vendor,
)

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.ingestion import NormalizedIntake
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.document_extraction import DocumentExtractionAgent, ExtractionRequest
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_FIFTEENTH_TYPE_ID = "delivery_confirmation"
"""Not one of the fourteen canonical `document_type_ids` constants —
deliberately invented here, and here only, to prove the registry is
genuinely open (spec §5.4: "adding a document type means adding a schema
and an edge mapping, not modifying the pipeline")."""


def _fifteenth_type_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_id=_FIFTEENTH_TYPE_ID,
        detection_signals=("courier_name", "delivery_confirmation_language", "tracking_number"),
        field_schema=(
            FieldSchema(name="courier", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="tracking_number", field_type="string", required=True, confidence_floor=0.70),
        ),
        target_node_types=("VENDOR",),
        target_edge_types=(),
        downstream_subsystems=("ledger",),
        verification_duties=("delivery_confirmation",),
    )


class _FifteenthTypeStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy` —
    a plain class, no special-casing anywhere else in the pipeline."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        courier_field = next(f for f in extracted_fields if f.name == "courier")
        vendor = Vendor(
            id=NodeId(f"vendor:{courier_field.value}"),
            provenance=Provenance(
                derivation=courier_field.derivation,
                source_ref=SourceRef(
                    source_document_id=source_document_id, region=courier_field.source_region
                ),
                confidence=courier_field.confidence,
                deriving_agent=deriving_agent,
                created_at=datetime.now(UTC),
            ),
            category="courier",
            contacts=(),
            reliability_score=None,
            response_latency_hours=None,
        )
        return GraphMappingResult(nodes=(vendor,), edges=())


def _intake() -> NormalizedIntake:
    return NormalizedIntake(
        channel="email",
        raw_payload_ref="sha256:cafebabe",
        text_content="Your parcel via BlueDart, tracking BD123456789, was delivered today.",
        media_type="text/plain",
        received_at=datetime(2026, 8, 20, tzinfo=UTC),
        sender="noreply@bluedart.example",
        participants=(),
        original_language_hint=None,
    )


class TestPipelineExtensibility:
    def test_fifteenth_type_routes_and_extracts_through_unmodified_pipeline_code(self) -> None:
        # 1. Build a registry with the real fourteen PLUS the fictional
        #    fifteenth — `register_all_strategies` and `DocumentTypeRegistry`
        #    are used completely unmodified.
        registry = DocumentTypeRegistry()
        register_all_strategies(registry)
        registry.register(_FIFTEENTH_TYPE_ID, _fifteenth_type_spec(), _FifteenthTypeStrategy())
        assert len(registry) == 15

        # 2. Route through A2 (unmodified) — the model "discovers" the new
        #    type from the candidate list A2 builds dynamically off
        #    registry.known_type_ids(), never a hardcoded type list.
        gap_log = RegistryGapLog(InMemoryRegistryGapStore())
        router_fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "type_id": _FIFTEENTH_TYPE_ID,
                        "type_confidence": 0.9,
                        "signals_matched": ["courier_name", "tracking_number"],
                        "runner_up_type_id": None,
                        "runner_up_confidence": 0.0,
                        "relevance": "relevant",
                        "relevance_reason": "Delivery confirmation.",
                    }
                )
            ]
        )
        intake_router = IntakeRouter(
            gemini_client=GeminiClient(router=fake_router(router_fake_models)),
            registry=registry,
            gap_log=gap_log,
        )
        route_result = intake_router.route(_intake())

        assert route_result.resolved is True
        assert route_result.classified_type_id == _FIFTEENTH_TYPE_ID
        assert gap_log.list_gaps() == ()  # a real registered type — no gap

        # 3. Extract through A3 (unmodified) — schema-driven off whatever
        #    DocumentTypeSpec the registry resolved, exactly as for the
        #    real fourteen types.
        assert route_result.classified_type_id is not None
        spec, strategy = registry.resolve(route_result.classified_type_id)
        extraction_fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "fields": [
                            {"name": "courier", "value": "BlueDart", "confidence": 0.9, "region": "10-18"},
                            {
                                "name": "tracking_number",
                                "value": "BD123456789",
                                "confidence": 0.9,
                                "region": "28-39",
                            },
                        ],
                        "fields_not_found": [],
                        "degraded_input_observed": False,
                    }
                )
            ]
        )
        extraction_client = GeminiClient(router=fake_router(extraction_fake_models))
        extraction_agent = DocumentExtractionAgent(gemini_client=extraction_client)
        extraction_result = extraction_agent.extract(
            ExtractionRequest(
                source_document_id=NodeId("doc-15th"),
                type_id=spec.type_id,
                field_schema=spec.field_schema,
                text_content="Your parcel via BlueDart, tracking BD123456789, was delivered today.",
            )
        )
        assert len(extraction_result.extracted_fields) == 2

        # 4. Map through the strategy (unmodified pipeline call shape).
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("doc-15th"),
            extracted_fields=extraction_result.extracted_fields,
            deriving_agent=AgentId("A3"),
        )
        assert len(mapping.nodes) == 1
        assert isinstance(mapping.nodes[0], Vendor)

"""Tests for A3 Document Extraction Agent
(`app.agents.intake.document_extraction`).

spec §15.2 A3: schema-driven, generic across all 14 types; field-level
confidence + source-region pointers; Flash for clean, Pro-tier for
degraded; **forbidden: inferring anything not literally present.**
"""

from __future__ import annotations

import json

import pytest
from contracts.agents import ModelTier
from contracts.graph_types import Derivation, FieldSchema, NodeId

from app.agents.intake import document_extraction as document_extraction_module
from app.agents.intake.document_extraction import DocumentExtractionAgent, ExtractionRequest
from app.agents.intake.errors import ModelResponseMalformed
from app.reasoning.gemini_client import GeminiClient, MediaPart

from ._ast_checks import imports_any_module_named, references_derivation_inferred
from ._gemini_fakes import FakeModels, fake_router

_SIMPLE_SCHEMA = (
    FieldSchema(name="merchant_name", field_type="string", required=True, confidence_floor=0.70),
    FieldSchema(name="total", field_type="number", required=True, confidence_floor=0.80),
)
_TEXT_BODY = "x" * 30


def _agent(texts: list[dict[str, object]]) -> DocumentExtractionAgent:
    fake_models = FakeModels(texts=[json.dumps(t) for t in texts])
    client = GeminiClient(router=fake_router(fake_models))
    return DocumentExtractionAgent(gemini_client=client)


def _text_request(media: tuple[MediaPart, ...] = ()) -> ExtractionRequest:
    if media:
        return ExtractionRequest(
            source_document_id=NodeId("doc-1"), type_id="receipt", field_schema=_SIMPLE_SCHEMA, media=media
        )
    return ExtractionRequest(
        source_document_id=NodeId("doc-1"),
        type_id="receipt",
        field_schema=_SIMPLE_SCHEMA,
        text_content=_TEXT_BODY,
    )


def _field(name: str, value: object, confidence: float, region: str) -> dict[str, object]:
    return {"name": name, "value": value, "confidence": confidence, "region": region}


class TestBasicExtraction:
    def test_extracts_fields_above_floor_as_extracted(self) -> None:
        agent = _agent(
            [
                {
                    "fields": [
                        _field("merchant_name", "Big Bazaar", 0.95, "0-10"),
                        _field("total", 450.0, 0.9, "20-25"),
                    ],
                    "fields_not_found": [],
                    "degraded_input_observed": False,
                }
            ]
        )
        result = agent.extract(_text_request())

        assert len(result.extracted_fields) == 2
        assert all(f.derivation is Derivation.EXTRACTED for f in result.extracted_fields)
        assert result.agent_output.model_tier is ModelTier.FLASH
        assert not result.escalated_to_pro

    def test_below_floor_field_is_marked_ambiguous_never_discarded(self) -> None:
        """Code-enforced, not model-trusted: even though the model itself
        did not flag this field, comparing its confidence against the
        schema's floor in code marks it AMBIGUOUS."""
        agent = _agent(
            [
                {
                    "fields": [
                        _field("merchant_name", "Big Bazaar", 0.95, "0-10"),
                        # total's floor is 0.80 — 0.40 must surface ambiguous.
                        _field("total", 450.0, 0.40, "20-25"),
                    ],
                    "fields_not_found": [],
                    "degraded_input_observed": False,
                }
            ]
        )
        result = agent.extract(_text_request())

        total_field = next(f for f in result.extracted_fields if f.name == "total")
        assert total_field.derivation is Derivation.AMBIGUOUS
        assert total_field.confidence == 0.40  # never silently rounded up
        assert total_field.value == 450.0  # retained, never discarded

    def test_field_with_unknown_name_is_dropped_not_trusted(self) -> None:
        agent = _agent(
            [
                {
                    "fields": [
                        _field("merchant_name", "Big Bazaar", 0.95, "0-10"),
                        _field("invented_field_not_in_schema", "x", 0.9, "0-1"),
                    ],
                    "fields_not_found": ["total"],
                    "degraded_input_observed": False,
                }
            ]
        )
        result = agent.extract(_text_request())

        names = {f.name for f in result.extracted_fields}
        assert "invented_field_not_in_schema" not in names
        assert "invented_field_not_in_schema" in result.fields_dropped_unknown_name
        assert "total" in result.fields_not_found

    def test_field_with_malformed_region_is_dropped(self) -> None:
        agent = _agent(
            [
                {
                    "fields": [_field("merchant_name", "Big Bazaar", 0.95, "not-a-region")],
                    "fields_not_found": ["total"],
                    "degraded_input_observed": False,
                }
            ]
        )
        result = agent.extract(_text_request())

        assert result.extracted_fields == ()
        assert "merchant_name" in result.fields_dropped_invalid_region


class TestTierEscalation:
    def test_degraded_flash_pass_triggers_pro_escalation(self) -> None:
        flash_response = {
            "fields": [_field("merchant_name", "???", 0.3, "page=1;bbox=0,0,1,1")],
            "fields_not_found": ["total"],
            "degraded_input_observed": True,
        }
        pro_response = {
            "fields": [
                _field("merchant_name", "Big Bazaar", 0.9, "page=1;bbox=0,0,1,1"),
                _field("total", 450.0, 0.85, "page=1;bbox=1,1,2,2"),
            ],
            "fields_not_found": [],
            "degraded_input_observed": True,
        }
        agent = _agent([flash_response, pro_response])
        media = (MediaPart(data=b"fake-image-bytes", mime_type="image/png"),)
        result = agent.extract(_text_request(media=media))

        assert result.escalated_to_pro is True
        assert result.agent_output.model_tier is ModelTier.PRO
        # the PRO pass's result is what's actually used, not the flash pass
        assert {f.name for f in result.extracted_fields} == {"merchant_name", "total"}

    def test_clean_flash_pass_never_escalates(self) -> None:
        agent = _agent(
            [
                {
                    "fields": [
                        _field("merchant_name", "Big Bazaar", 0.95, "0-10"),
                        _field("total", 450.0, 0.9, "20-25"),
                    ],
                    "fields_not_found": [],
                    "degraded_input_observed": False,
                }
            ]
        )
        result = agent.extract(_text_request())
        assert result.escalated_to_pro is False
        assert result.agent_output.model_tier is ModelTier.FLASH


class TestMalformedResponse:
    def test_non_json_response_raises_typed_error(self) -> None:
        fake_models = FakeModels(texts=["not json at all {{{"])
        client = GeminiClient(router=fake_router(fake_models))
        broken_agent = DocumentExtractionAgent(gemini_client=client)
        with pytest.raises(ModelResponseMalformed):
            broken_agent.extract(_text_request())


class TestExtractionRequestValidation:
    def test_requires_exactly_one_of_text_or_media(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            ExtractionRequest(
                source_document_id=NodeId("doc-1"), type_id="receipt", field_schema=_SIMPLE_SCHEMA
            )
        with pytest.raises(ValueError, match="exactly one"):
            ExtractionRequest(
                source_document_id=NodeId("doc-1"),
                type_id="receipt",
                field_schema=_SIMPLE_SCHEMA,
                text_content="hello",
                media=(MediaPart(data=b"x", mime_type="image/png"),),
            )


class TestNeverInfers:
    """spec §15.2 A3's single most safety-critical forbidden item:
    extraction never infers. Enforced structurally: this module's own
    source code never constructs `Derivation.INFERRED` anywhere — a
    code-review-style assertion, not just a runtime behavioural test."""

    def test_module_source_never_references_derivation_inferred(self) -> None:
        assert not references_derivation_inferred(document_extraction_module)

    def test_extraction_and_implication_are_architecturally_separate_modules(self) -> None:
        """A3 (this module) has no import path to any Phase-4 implication
        module — Phase 4 does not exist yet in this codebase, so the
        strongest available proof is that this module's actual `import`
        statements name nothing `implication`-related (checked via AST,
        not a substring scan of the docstrings that *discuss* the rule)."""
        assert not imports_any_module_named(document_extraction_module, substring="implication")

"""Tests for A3b Line-Item Extraction Agent
(`app.agents.intake.line_item_extraction`) and its deterministic category
normalizer (`app.agents.intake.category_normalization`).

spec §15.2 A3b: per-line description/quantity/unit price/tax; product-
category normalisation across merchants; Pro-tier for degraded thermal
receipts; forbidden: inferring items not printed, guessing quantities;
partial extraction ("10 of 12 lines read") is fine, fabricated lines are
poison.
"""

from __future__ import annotations

import json

from contracts.agents import ModelTier
from contracts.graph_types import Derivation, NodeId

from app.agents.intake import line_item_extraction as line_item_extraction_module
from app.agents.intake.category_normalization import normalize_category
from app.agents.intake.line_item_extraction import (
    LineItemExtractionAgent,
    LineItemExtractionRequest,
    build_line_items_field,
)
from app.reasoning.gemini_client import GeminiClient, MediaPart

from ._ast_checks import references_derivation_inferred
from ._gemini_fakes import FakeModels, fake_router


class TestCategoryNormalization:
    def test_amul_taaza_and_milk_litre_resolve_to_same_category(self) -> None:
        """spec §5.4.2's own example."""
        assert normalize_category("AMUL TAAZA 1L") == normalize_category("Milk 1 litre")
        assert normalize_category("AMUL TAAZA 1L") == "dairy_and_milk"

    def test_unrecognised_description_returns_none_never_guesses(self) -> None:
        assert normalize_category("XZQJ-9981-PROMO-CODE") is None

    def test_case_insensitive(self) -> None:
        assert normalize_category("BREAD LOAF") == normalize_category("bread loaf")


def _agent(texts: list[dict[str, object]]) -> LineItemExtractionAgent:
    fake_models = FakeModels(texts=[json.dumps(t) for t in texts])
    client = GeminiClient(router=fake_router(fake_models))
    return LineItemExtractionAgent(gemini_client=client)


class TestLineItemExtraction:
    def test_extracts_multiple_lines_with_category_normalization(self) -> None:
        agent = _agent(
            [
                {
                    "line_items": [
                        {
                            "description": "AMUL TAAZA 1L",
                            "quantity": 2,
                            "unit_price": 30.0,
                            "line_total": 60.0,
                            "tax": None,
                            "confidence": 0.9,
                            "region": "0-20",
                        },
                        {
                            "description": "Bread loaf",
                            "quantity": 1,
                            "unit_price": 40.0,
                            "line_total": 40.0,
                            "tax": None,
                            "confidence": 0.85,
                            "region": "20-35",
                        },
                    ],
                    "lines_expected_total": 2,
                    "degraded_input_observed": False,
                }
            ]
        )
        request = LineItemExtractionRequest(source_document_id=NodeId("doc-1"), text_content="x" * 40)
        result = agent.extract(request)

        assert result.lines_read == 2
        assert result.is_partial is False
        assert result.line_items[0].normalized_category == "dairy_and_milk"
        assert result.line_items[1].normalized_category == "bakery"
        assert all(item.derivation is Derivation.EXTRACTED for item in result.line_items)

    def test_partial_extraction_is_flagged_not_fabricated(self) -> None:
        """'10 of 12 lines read' is acceptable and must be visible."""
        agent = _agent(
            [
                {
                    "line_items": [
                        {
                            "description": "Rice 5kg",
                            "quantity": 1,
                            "unit_price": 250.0,
                            "line_total": 250.0,
                            "tax": None,
                            "confidence": 0.8,
                            "region": "0-10",
                        }
                    ],
                    "lines_expected_total": 3,
                    "degraded_input_observed": True,
                }
            ]
        )
        request = LineItemExtractionRequest(
            source_document_id=NodeId("doc-1"), media=(MediaPart(data=b"img", mime_type="image/png"),)
        )
        result = agent.extract(request)

        assert result.lines_read == 1
        assert result.lines_expected_total == 3
        assert result.is_partial is True
        # Only exactly what was returned — nothing fabricated to fill the gap.
        assert len(result.line_items) == 1

    def test_below_floor_line_marked_ambiguous(self) -> None:
        agent = _agent(
            [
                {
                    "line_items": [
                        {
                            "description": "Smudged item",
                            "quantity": None,
                            "unit_price": None,
                            "line_total": 99.0,
                            "tax": None,
                            "confidence": 0.2,
                            "region": "page=1;bbox=1,1,2,2",
                        }
                    ],
                    "lines_expected_total": 1,
                    "degraded_input_observed": True,
                }
            ]
        )
        request = LineItemExtractionRequest(
            source_document_id=NodeId("doc-1"),
            media=(MediaPart(data=b"img", mime_type="image/png"),),
            confidence_floor=0.70,
        )
        result = agent.extract(request)
        assert result.line_items[0].derivation is Derivation.AMBIGUOUS

    def test_degraded_thermal_receipt_escalates_to_pro(self) -> None:
        flash_response: dict[str, object] = {
            "line_items": [],
            "lines_expected_total": None,
            "degraded_input_observed": True,
        }
        pro_response: dict[str, object] = {
            "line_items": [
                {
                    "description": "Recovered item",
                    "quantity": 1,
                    "unit_price": 10.0,
                    "line_total": 10.0,
                    "tax": None,
                    "confidence": 0.75,
                    "region": "page=1;bbox=0,0,5,5",
                }
            ],
            "lines_expected_total": 1,
            "degraded_input_observed": True,
        }
        agent = _agent([flash_response, pro_response])
        request = LineItemExtractionRequest(
            source_document_id=NodeId("doc-1"), media=(MediaPart(data=b"img", mime_type="image/png"),)
        )
        result = agent.extract(request)

        assert result.escalated_to_pro is True
        assert result.agent_output.model_tier is ModelTier.PRO
        assert result.lines_read == 1

    def test_build_line_items_field_packages_typed_tuple(self) -> None:
        agent = _agent(
            [
                {
                    "line_items": [
                        {
                            "description": "Rice 5kg",
                            "quantity": 1,
                            "unit_price": 250.0,
                            "line_total": 250.0,
                            "tax": None,
                            "confidence": 0.9,
                            "region": "0-10",
                        }
                    ],
                    "lines_expected_total": 1,
                    "degraded_input_observed": False,
                }
            ]
        )
        request = LineItemExtractionRequest(source_document_id=NodeId("doc-1"), text_content="x" * 20)
        result = agent.extract(request)
        field = build_line_items_field(result)

        assert field.name == "line_items"
        assert field.value == result.line_items


class TestNeverInfersOrFabricates:
    def test_module_source_never_references_derivation_inferred(self) -> None:
        assert not references_derivation_inferred(line_item_extraction_module)

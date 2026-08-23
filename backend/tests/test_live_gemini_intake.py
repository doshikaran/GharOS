"""Live Vertex AI integration tests for the Phase 3 intake agents —
real Gemini calls, real network access, no fakes. Matches this repo's
established `live_gcp` convention (`test_gemini_client.py`,
`test_secret_manager_adapter.py`): skipped by default so the rest of the
suite never needs live credentials or makes a real network call.

    GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=<project> \\
        uv run pytest tests/test_live_gemini_intake.py -m live_gcp -v

These three calls are deliberately representative rather than exhaustive
(cost discipline, spec §21.1): one real multimodal call (A3, the highest-
value thing to prove against a real model — synthetic image bytes really
sent, real fields really read back), one real text-classification call
(A2), and one real cross-script entity-resolution call (A5, spec §21.1's
own named "cross-script entity resolution" live-Gemini use case).

**Assertions here are deliberately loose** (field presence, plausible
shape) rather than exact-string-equality — a real model's phrasing varies
between calls in ways a hand-authored fake response never does; the
point of these tests is proving the real plumbing works end-to-end, not
re-asserting the golden suite's exact-value checks against a
non-deterministic API.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
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

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.ingestion import NormalizedIntake
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.document_extraction import DocumentExtractionAgent, ExtractionRequest
from app.agents.intake.entity_resolution import EntityResolutionAgent, ResolutionVerdict
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.reasoning.gemini_client import GeminiClient, MediaPart
from app.reasoning.model_router import ModelRouter
from app.settings import Settings

from .golden import image_fixtures as img

_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
_SKIP_REASON = (
    "live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID "
    "to run real Gemini calls against Vertex AI"
)


def _live_router() -> ModelRouter:
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    return ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )


def _registry() -> DocumentTypeRegistry:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    return registry


@pytest.mark.live_gcp
@pytest.mark.skipif(not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID, reason=_SKIP_REASON)
def test_a3_real_multimodal_extraction_reads_a_synthetic_receipt_image() -> None:
    """Real Vertex AI Gemini multimodal call: sends the actual PNG bytes
    of a synthetic (Pillow-rendered, deliberately messy) receipt and
    asserts the real model reads back plausible field values."""
    client = GeminiClient(router=_live_router())
    agent = DocumentExtractionAgent(gemini_client=client)
    registry = _registry()
    spec, _strategy = registry.resolve("receipt")

    doc = img.receipt_grocery()
    request = ExtractionRequest(
        source_document_id=NodeId("live-receipt-1"),
        type_id="receipt",
        field_schema=spec.field_schema,
        media=(MediaPart(data=doc.png_bytes, mime_type="image/png"),),
    )
    result = agent.extract(request)

    assert result.extracted_fields, "real model returned no fields at all"
    field_names = {f.name for f in result.extracted_fields}
    # The real model should find at least the merchant name and total —
    # both large, unambiguous printed text on the fixture.
    assert "merchant_name" in field_names or "total" in field_names
    for extracted_field in result.extracted_fields:
        assert 0.0 <= extracted_field.confidence <= 1.0
        assert extracted_field.derivation in (Derivation.EXTRACTED, Derivation.AMBIGUOUS)
        assert extracted_field.source_region  # never empty


@pytest.mark.live_gcp
@pytest.mark.skipif(not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID, reason=_SKIP_REASON)
def test_a2_real_classification_of_a_receipt_like_text() -> None:
    """Real Vertex AI Gemini text-classification call: A2 against a
    receipt-shaped plain-text item, using the real registered candidate
    type list (not a fake)."""
    router = _live_router()
    client = GeminiClient(router=router)
    intake_router = IntakeRouter(
        gemini_client=client, registry=_registry(), gap_log=RegistryGapLog(InMemoryRegistryGapStore())
    )
    intake = NormalizedIntake(
        channel="email",
        raw_payload_ref="sha256:live-test",
        text_content=(
            "BIG BAZAAR SUPERMARKET\nAndheri West, Mumbai\nDate: 2026-08-15 10:30\n"
            "AMUL TAAZA 1L        x2    60.00\nBREAD LOAF           x1    40.00\n"
            "TOTAL:              100.00\nPAYMENT: UPI"
        ),
        media_type="text/plain",
        received_at=datetime(2026, 8, 20, tzinfo=UTC),
        sender="store@example.org",
        participants=(),
        original_language_hint=None,
    )
    result = intake_router.route(intake)

    assert result.classified_type_id is not None
    # Real receipt text should classify as receipt with reasonable confidence.
    assert result.classified_type_id == "receipt"
    assert result.type_confidence > 0.3


@pytest.mark.live_gcp
@pytest.mark.skipif(not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID, reason=_SKIP_REASON)
def test_a5_real_cross_script_entity_resolution() -> None:
    """Real Vertex AI Gemini call: spec §21.1's own named live-Gemini use
    case — resolving आरव / Aarav / Arav against one known PERSON."""
    client = GeminiClient(router=_live_router())
    agent = EntityResolutionAgent(gemini_client=client)

    known_person = Person(
        id=NodeId("person-aarav-live"),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("seed"), region="0-1"),
            confidence=0.99,
            deriving_agent=AgentId("A0"),
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        ),
        display_name="Aarav",
        aliases=("आरव", "Arav"),
        role=PersonRole.CHILD,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
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

    results = []
    for mention in ("आरव", "Aarav", "Arav"):
        result = agent.resolve(
            mention_text=mention,
            mention_context="school pickup arrangement for the child",
            known_people=(known_person,),
        )
        results.append((mention, result))

    for mention, result in results:
        assert result.resolution in (ResolutionVerdict.MATCHED_EXISTING, ResolutionVerdict.AMBIGUOUS), (
            f"real model gave an unexpected verdict for {mention!r}: {result.resolution}"
        )
        if result.resolution is ResolutionVerdict.MATCHED_EXISTING:
            assert result.matched_person_id == NodeId("person-aarav-live")

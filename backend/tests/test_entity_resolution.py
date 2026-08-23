"""Tests for A5 Entity Resolution Agent
(`app.agents.intake.entity_resolution`).

spec §15.2 A5 / §21.1: cross-script alias resolution ("आरव", "Aarav",
"Arav" -> one PERSON), Flash with Pro-tier escalation on ambiguity,
forbidden: creating entities above a confidence threshold without
confirmation, **never guess on hard-constraint-bearing entities.**

**Gate 3 planted case, satisfied here:** `test_cross_script_aliases_all_resolve_to_the_same_person`
covers PHASES.md Phase 3's explicit checklist item "आरव / Aarav / Arav ->
one PERSON" for all three spellings against one known household PERSON.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.agents import ModelTier
from contracts.errors import AmbiguousEntity
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

from app.agents.intake.entity_resolution import EntityResolutionAgent, ResolutionVerdict
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _person(node_id: str, display_name: str, aliases: tuple[str, ...] = ()) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("seed"), region="0-1"),
            confidence=0.99,
            deriving_agent=AgentId("A0"),
            created_at=_NOW,
        ),
        display_name=display_name,
        aliases=aliases,
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


_AARAV = _person("person-aarav", "Aarav", aliases=("आरव", "Arav"))
_KNOWN_PEOPLE = (_AARAV,)


def _agent(response_obj: dict[str, object]) -> EntityResolutionAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return EntityResolutionAgent(gemini_client=client)


class TestCrossScriptResolution:
    @pytest.mark.parametrize("mention", ["आरव", "Aarav", "Arav"])
    def test_cross_script_aliases_all_resolve_to_the_same_person(self, mention: str) -> None:
        agent = _agent(
            {
                "resolution": "matched_existing",
                "matched_person_id": "person-aarav",
                "candidate_person_ids": [],
                "reasoning": f"'{mention}' is a known transliteration/script variant of Aarav's aliases.",
                "confidence": 0.95,
            }
        )
        result = agent.resolve(
            mention_text=mention, mention_context="school pickup", known_people=_KNOWN_PEOPLE
        )

        assert result.resolution is ResolutionVerdict.MATCHED_EXISTING
        assert result.matched_person_id == NodeId("person-aarav")


class TestAmbiguityEscalation:
    def test_ambiguous_flash_result_escalates_to_pro(self) -> None:
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "resolution": "ambiguous",
                        "matched_person_id": None,
                        "candidate_person_ids": ["person-aarav", "person-other"],
                        "reasoning": "Could be either.",
                        "confidence": 0.4,
                    }
                ),
                json.dumps(
                    {
                        "resolution": "matched_existing",
                        "matched_person_id": "person-aarav",
                        "candidate_person_ids": [],
                        "reasoning": "Pro-tier pass resolved it via context.",
                        "confidence": 0.9,
                    }
                ),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = EntityResolutionAgent(gemini_client=client)

        result = agent.resolve(mention_text="Arav", mention_context="x", known_people=_KNOWN_PEOPLE)

        assert result.escalated_to_pro is True
        assert result.agent_output.model_tier is ModelTier.PRO
        assert result.resolution is ResolutionVerdict.MATCHED_EXISTING

    def test_hard_constraint_low_confidence_flash_forces_pro_escalation(self) -> None:
        """Even a *confident-sounding* Flash 'matched_existing' is not
        trusted alone when `hard_constraint_context` is True and
        confidence is below the hard-constraint floor."""
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "resolution": "matched_existing",
                        "matched_person_id": "person-aarav",
                        "candidate_person_ids": [],
                        "reasoning": "Weak match.",
                        "confidence": 0.6,
                    }
                ),
                json.dumps(
                    {
                        "resolution": "matched_existing",
                        "matched_person_id": "person-aarav",
                        "candidate_person_ids": [],
                        "reasoning": "Confirmed on closer inspection.",
                        "confidence": 0.92,
                    }
                ),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = EntityResolutionAgent(gemini_client=client)

        result = agent.resolve(
            mention_text="Arav",
            mention_context="allergy note",
            known_people=_KNOWN_PEOPLE,
            hard_constraint_context=True,
        )
        assert result.escalated_to_pro is True


class TestNeverGuessOnHardConstraint:
    def test_still_ambiguous_after_pro_escalation_raises_never_returns_a_guess(self) -> None:
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "resolution": "ambiguous",
                        "matched_person_id": None,
                        "candidate_person_ids": ["person-aarav", "person-other"],
                        "reasoning": "Still unclear at Flash tier.",
                        "confidence": 0.3,
                    }
                ),
                json.dumps(
                    {
                        "resolution": "ambiguous",
                        "matched_person_id": None,
                        "candidate_person_ids": ["person-aarav", "person-other"],
                        "reasoning": "Still unclear even at Pro tier.",
                        "confidence": 0.35,
                    }
                ),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = EntityResolutionAgent(gemini_client=client)

        with pytest.raises(AmbiguousEntity) as exc_info:
            agent.resolve(
                mention_text="Arav",
                mention_context="nut allergy note",
                known_people=_KNOWN_PEOPLE,
                hard_constraint_context=True,
            )
        assert exc_info.value.hard_constraint_bearing is True

    def test_non_hard_constraint_ambiguous_result_is_returned_not_raised(self) -> None:
        """Ambiguity is only a hard failure when hard_constraint_context
        is True — otherwise it is a normal, informative result."""
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "resolution": "ambiguous",
                        "matched_person_id": None,
                        "candidate_person_ids": ["person-aarav", "person-other"],
                        "reasoning": "Unclear.",
                        "confidence": 0.4,
                    }
                ),
                json.dumps(
                    {
                        "resolution": "ambiguous",
                        "matched_person_id": None,
                        "candidate_person_ids": ["person-aarav", "person-other"],
                        "reasoning": "Still unclear.",
                        "confidence": 0.4,
                    }
                ),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = EntityResolutionAgent(gemini_client=client)

        result = agent.resolve(mention_text="Arav", mention_context="x", known_people=_KNOWN_PEOPLE)
        assert result.resolution is ResolutionVerdict.AMBIGUOUS

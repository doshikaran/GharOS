"""Tests for A12 Implication Agent (`app.agents.consequence.implication_agent`).

spec §7.3 Stage 2 / §15.4 A12, PHASES.md Gate 4's own acceptance list:
- Canonical field-trip email -> >=5 implied obligations with valid citations.
- Every implied obligation has a verified, resolvable source span.
- Adversarial: a document designed to tempt an uncitable inference ->
  discarded and logged, never surfaced.

Unit tests only (fake Gemini, no network) — the real-Gemini version of the
canonical case lives in `test_live_gemini_consequence.py`, `live_gcp`-marked.
"""

from __future__ import annotations

import json

from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from app.agents.consequence.implication_agent import AGENT_ID, ImplicationAgent
from app.agents.consequence.types import HouseholdContext, ImplicationRequest
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import make_person

from ._gemini_fakes import FakeModels, fake_router

_FIELD_TRIP_TEXT = (
    "Field trip Friday. Signed permission slip due Wednesday. ₹500 fee. "
    "Nut-free lunch required. Early pickup 1:30pm."
)

_EMPTY_CONTEXT = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())


def _agent(response_obj: dict[str, object]) -> ImplicationAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return ImplicationAgent(gemini_client=client)


def _request(document_text: str, *, context: HouseholdContext | None = None) -> ImplicationRequest:
    return ImplicationRequest(
        source_document_id=NodeId("doc-field-trip"),
        document_text=document_text,
        household_context=context or _EMPTY_CONTEXT,
    )


_FIVE_VALID_CANDIDATES: list[dict[str, object]] = [
    {
        "label": "sign_slip",
        "title": "Sign and return the permission slip",
        "obligation_type": "permission_slip",
        "due_at": None,
        "effort_estimate_minutes": 5,
        "reasoning": "The slip is due Wednesday and needs a parent's signature.",
        "cited_span_text": "Signed permission slip due Wednesday",
        "confidence": 0.9,
        "depends_on_labels": [],
    },
    {
        "label": "cash_fee",
        "title": "Get ₹500 cash for the field trip fee",
        "obligation_type": "payment",
        "due_at": None,
        "effort_estimate_minutes": 15,
        "reasoning": "The fee must be paid in cash before the trip.",
        "cited_span_text": "₹500 fee",
        "confidence": 0.85,
        "depends_on_labels": ["sign_slip"],
    },
    {
        "label": "menu_check",
        "title": "Check Friday's lunch plan against the nut-free requirement",
        "obligation_type": "menu_substitution",
        "due_at": None,
        "effort_estimate_minutes": 10,
        "reasoning": "The trip requires a nut-free lunch, which must be checked against what is planned.",
        "cited_span_text": "Nut-free lunch required",
        "confidence": 0.88,
        "depends_on_labels": [],
    },
    {
        "label": "pickup_coverage",
        "title": "Arrange coverage for the 1:30pm early pickup",
        "obligation_type": "coverage_needed",
        "due_at": None,
        "effort_estimate_minutes": 20,
        "reasoning": "Pickup is earlier than usual and the regular pickup person may not be free.",
        "cited_span_text": "Early pickup 1:30pm",
        "confidence": 0.8,
        "depends_on_labels": [],
    },
    {
        "label": "cancel_activity",
        "title": "Cancel or reschedule the regular Friday after-school activity",
        "obligation_type": "cancellation",
        "due_at": None,
        "effort_estimate_minutes": 5,
        "reasoning": "The field trip is on Friday, which is also when a regular activity happens.",
        "cited_span_text": "Field trip Friday",
        "confidence": 0.75,
        "depends_on_labels": [],
    },
]


class TestCanonicalFieldTripCase:
    def test_at_least_five_implied_obligations_with_valid_citations(self) -> None:
        agent = _agent({"candidates": _FIVE_VALID_CANDIDATES})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))

        assert len(result.candidates) >= 5
        assert result.discarded == ()
        for candidate in result.candidates:
            assert candidate.cited_span_text in _FIELD_TRIP_TEXT
            assert candidate.citation.region  # never empty
            start, end = (int(part) for part in candidate.citation.region.split("-"))
            resolved = _FIELD_TRIP_TEXT.encode("utf-8")[start:end].decode("utf-8")
            assert resolved == candidate.cited_span_text

    def test_every_candidate_source_document_id_matches_request(self) -> None:
        agent = _agent({"candidates": _FIVE_VALID_CANDIDATES})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))
        for candidate in result.candidates:
            assert candidate.citation.source_document_id == "doc-field-trip"

    def test_model_tier_and_prompt_version_recorded(self) -> None:
        agent = _agent({"candidates": _FIVE_VALID_CANDIDATES})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))
        assert result.model_tier == "pro"
        assert result.prompt_version == "v1"

    def test_dependency_labels_resolve_to_real_candidate_ids(self) -> None:
        agent = _agent({"candidates": _FIVE_VALID_CANDIDATES})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))

        by_title = {c.title: c for c in result.candidates}
        cash_fee = by_title["Get ₹500 cash for the field trip fee"]
        sign_slip = by_title["Sign and return the permission slip"]
        assert cash_fee.depends_on_candidate_ids == (sign_slip.candidate_id,)


class TestUncitableInferenceDiscarded:
    """The mandatory rule, tested directly: an uncitable inference is
    discarded, never surfaced 'at low confidence'."""

    def test_fabricated_citation_is_discarded_not_surfaced(self) -> None:
        candidates: list[dict[str, object]] = [
            {
                "label": "invented",
                "title": "Bring a helmet for the bus ride",
                "obligation_type": "errand",
                "due_at": None,
                "effort_estimate_minutes": 5,
                "reasoning": "Buses can be dangerous so a helmet seems wise.",
                "cited_span_text": "All students must wear a safety helmet on the bus",
                "confidence": 0.95,
                "depends_on_labels": [],
            }
        ]
        agent = _agent({"candidates": candidates})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))

        assert result.candidates == ()
        assert len(result.discarded) == 1
        discarded = result.discarded[0]
        assert discarded.title == "Bring a helmet for the bus ride"
        assert discarded.discard_reason  # non-empty, specific
        assert "not found" in discarded.discard_reason or "not located" in discarded.discard_reason

    def test_a_high_confidence_uncitable_claim_is_still_discarded(self) -> None:
        """Confidence never rescues an uncitable claim — this is the
        precise 'low confidence, not discarded' failure mode the rule
        forbids: a confident-sounding fabrication must be discarded
        exactly like a hesitant one."""
        candidates: list[dict[str, object]] = [
            {
                "label": "invented_confident",
                "title": "Pack a spare uniform",
                "obligation_type": "errand",
                "due_at": None,
                "effort_estimate_minutes": 5,
                "reasoning": "Field trips sometimes get messy.",
                "cited_span_text": "Students should pack a spare uniform in case of spills",
                "confidence": 0.99,
                "depends_on_labels": [],
            }
        ]
        agent = _agent({"candidates": candidates})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))
        assert result.candidates == ()
        assert len(result.discarded) == 1

    def test_mixed_batch_only_discards_the_uncitable_one(self) -> None:
        candidates: list[dict[str, object]] = [
            _FIVE_VALID_CANDIDATES[0],
            {
                "label": "invented_mixed",
                "title": "Arrange a translator",
                "obligation_type": "errand",
                "due_at": None,
                "effort_estimate_minutes": 5,
                "reasoning": "Some trips need a translator.",
                "cited_span_text": "A translator will be provided for non-English speakers",
                "confidence": 0.7,
                "depends_on_labels": [],
            },
        ]
        agent = _agent({"candidates": candidates})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))
        assert len(result.candidates) == 1
        assert len(result.discarded) == 1
        assert result.candidates[0].title == "Sign and return the permission slip"


class TestLowConfidenceDiscarded:
    def test_low_confidence_candidate_with_valid_citation_still_discarded(self) -> None:
        candidates: list[dict[str, object]] = [
            {
                "label": "shaky",
                "title": "Maybe bring an umbrella",
                "obligation_type": "errand",
                "due_at": None,
                "effort_estimate_minutes": 2,
                "reasoning": "Weak inference.",
                "cited_span_text": "Field trip Friday",
                "confidence": 0.2,
                "depends_on_labels": [],
            }
        ]
        agent = _agent({"candidates": candidates})
        result = agent.imply(_request(_FIELD_TRIP_TEXT))
        assert result.candidates == ()
        assert len(result.discarded) == 1
        assert "confidence" in result.discarded[0].discard_reason


class TestEmptyCandidates:
    def test_empty_candidate_list_is_a_valid_result(self) -> None:
        agent = _agent({"candidates": []})
        result = agent.imply(_request("Nothing much happens in this document."))
        assert result.candidates == ()
        assert result.discarded == ()
        assert result.confidence == 0.0


class TestHouseholdContextRendersIntoPrompt:
    def test_people_and_constraints_are_included_in_the_call(self) -> None:
        person = make_person("person-priya", "Priya", can_sign=True)
        constraint = Constraint(
            id=NodeId("constraint-nut"),
            provenance=person.provenance,
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.HARD,
            validity_start=None,
            validity_end=None,
            structured={"allergen": "nut"},
            original_text="No nuts, ever.",
        )
        context = HouseholdContext(
            people=(person,), constraints=(constraint,), open_obligations=(), stated_obligations=()
        )
        fake_models = FakeModels(texts=[json.dumps({"candidates": []})])
        client = GeminiClient(router=fake_router(fake_models))
        agent = ImplicationAgent(gemini_client=client)

        agent.imply(_request(_FIELD_TRIP_TEXT, context=context))

        sent_prompt = str(fake_models.calls[0]["contents"])
        assert "Priya" in sent_prompt
        assert "No nuts, ever." in sent_prompt


class TestModelTierIsPro:
    def test_calls_at_pro_tier_with_elevated_thinking_budget(self) -> None:
        fake_models = FakeModels(texts=[json.dumps({"candidates": []})])
        router = fake_router(fake_models)
        client = GeminiClient(router=router)
        agent = ImplicationAgent(gemini_client=client)

        agent.imply(_request(_FIELD_TRIP_TEXT))

        assert AGENT_ID == "A12"
        call = fake_models.calls[0]
        assert call["model"] == "gemini-2.5-pro"
        config = call["config"]
        assert config is not None
        assert config.thinking_config is not None
        assert config.thinking_config.thinking_budget is not None
        assert config.thinking_config.thinking_budget > 0

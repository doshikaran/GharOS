"""Tests for A55 Confirmation Verifier
(`app.agents.concierge.confirmation_verifier_agent`).

PHASES.md Gate 10's single most safety-critical checklist item:
**"Unverified outcome never recorded — proven by test."** The structural
discrepancy logic itself is covered exhaustively in `test_verification.py`
(no Gemini mocking needed there at all); these tests cover the agent
wrapper's two-layer design and its adversarial-safety guarantees:

1. A discrepant `CallOutcomeReport` can never reach `verified=True`, even
   when the (fake, adversarial) model response claims otherwise.
2. The model can only ever narrow an already-passing structural verdict,
   never widen a failing one.
3. This module holds no write tool / `GraphWriter` of any kind (AST-based
   forbidden-import test, mirroring `test_blocker_diagnosis_agent.py`'s
   established pattern).
"""

from __future__ import annotations

import ast
import inspect
import json
import types
from datetime import UTC, datetime

from contracts.graph_types import NodeId

from app.agents.concierge import confirmation_verifier_agent
from app.agents.concierge.confirmation_verifier_agent import AGENT_ID, ConfirmationVerifierAgent
from app.agents.concierge.types import CallBrief, CallOutcomeReport
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_DATE_RANGE = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 10, tzinfo=UTC))
_PREFERRED_SLOTS = (datetime(2026, 9, 3, 16, 0, tzinfo=UTC),)


def _agent(texts: list[str] | None = None) -> tuple[ConfirmationVerifierAgent, FakeModels]:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return ConfirmationVerifierAgent(gemini_client=GeminiClient(router=fake_router(fake_models))), fake_models


def _brief() -> CallBrief:
    return CallBrief(
        target_provider_id=NodeId("provider-1"),
        person_id=NodeId("person-aarav"),
        objective="Book a routine dental cleaning for Aarav",
        date_range=_DATE_RANGE,
        price_ceiling=1500.0,
        disclosable_facts=("patient name: Aarav",),
        must_not_answer=("medical diagnosis",),
        preferred_slots=_PREFERRED_SLOTS,
        fallback_acceptable=True,
    )


def _report(**overrides: object) -> CallOutcomeReport:
    defaults: dict[str, object] = {
        "call_id": "call-1",
        "target_provider_id": NodeId("provider-1"),
        "transcript_source_document_id": NodeId("doc-transcript-1"),
        "disclosure_given": True,
        "claimed_slot": _PREFERRED_SLOTS[0],
        "claimed_outcome_summary": "Booked the requested dental cleaning slot.",
        "out_of_bounds_encountered": False,
        "requires_human_callback": False,
    }
    defaults.update(overrides)
    return CallOutcomeReport(**defaults)  # type: ignore[arg-type]


class TestStructuralFailureNeverReachesModel:
    """Cost discipline AND safety: when the structural check already
    fails, no Gemini call is made at all — nothing for a model to
    (mis)narrate its way around."""

    def test_wrong_date_fails_without_any_gemini_call(self) -> None:
        agent, fake_models = _agent()

        result = agent.verify(brief=_brief(), report=_report(claimed_slot=datetime(2026, 10, 1, tzinfo=UTC)))

        assert result.verified is False
        assert result.model_tier == "deterministic"
        assert fake_models.calls == []

    def test_disclosure_false_fails_without_any_gemini_call(self) -> None:
        agent, fake_models = _agent()

        result = agent.verify(brief=_brief(), report=_report(disclosure_given=False))

        assert result.verified is False
        assert fake_models.calls == []


class TestSemanticLayerOnlyNarrows:
    """The Pro-tier semantic check runs only once the structural check has
    already passed, and can only turn that pass into a fail — never the
    reverse."""

    def test_structurally_valid_but_semantically_implausible_fails(self) -> None:
        response = json.dumps(
            {
                "semantically_plausible": False,
                "explanation": "This describes a haircut, not a dental cleaning.",
                "confidence": 0.9,
            }
        )
        agent, _ = _agent(texts=[response])

        result = agent.verify(
            brief=_brief(), report=_report(claimed_outcome_summary="Booked a haircut for 4pm.")
        )

        assert result.verified is False
        assert result.model_tier == "pro"
        assert "semantic mismatch" in result.discrepancies[0]
        assert result.requires_human_callback is True

    def test_structurally_valid_and_semantically_plausible_verifies(self) -> None:
        response = json.dumps(
            {"semantically_plausible": True, "explanation": "Matches the objective.", "confidence": 0.95}
        )
        agent, _ = _agent(texts=[response])

        result = agent.verify(brief=_brief(), report=_report())

        assert result.verified is True
        assert result.discrepancies == ()


class TestAdversarialModelCannotFabricateVerification:
    """The single most safety-critical guarantee, proven directly: a
    discrepant `CallOutcomeReport` cannot reach `verified=True` no matter
    what a (adversarial) model response claims."""

    def test_bogus_verified_true_key_in_response_is_never_read(self) -> None:
        """The fake model response embeds an extra `"verified": true` key
        alongside a genuine `semantically_plausible: false` — the code
        must never read the bogus key; only `semantically_plausible`
        determines the outcome here, and it says no."""
        response = json.dumps(
            {
                "verified": True,  # adversarial: not a field this code ever reads
                "semantically_plausible": False,
                "explanation": "Outcome summary describes an unrelated service.",
                "confidence": 0.99,
            }
        )
        agent, _ = _agent(texts=[response])

        result = agent.verify(
            brief=_brief(), report=_report(claimed_outcome_summary="Picked up a prescription.")
        )

        assert result.verified is False

    def test_structural_discrepancy_cannot_be_overridden_by_any_model_response(self) -> None:
        """Even a maximally cooperative-looking fake model response
        (claiming full plausibility and high confidence) cannot rescue a
        structurally-discrepant report — the model is never even called
        in this branch, so its content is irrelevant by construction."""
        response = json.dumps(
            {"semantically_plausible": True, "explanation": "looks fine", "confidence": 1.0}
        )
        agent, fake_models = _agent(texts=[response])

        result = agent.verify(brief=_brief(), report=_report(target_provider_id=NodeId("provider-different")))

        assert result.verified is False
        assert fake_models.calls == []

    def test_out_of_bounds_encountered_cannot_be_talked_past(self) -> None:
        agent, fake_models = _agent()

        result = agent.verify(brief=_brief(), report=_report(out_of_bounds_encountered=True))

        assert result.verified is False
        assert result.requires_human_callback is True
        assert fake_models.calls == []


def _references_any_tool_or_graph_write_machinery(module: types.ModuleType) -> bool:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                "graph_write_tool" in node.module
                or "graph_read_tool" in node.module
                or ".registry" in node.module
                or "arbitration" in node.module
                or "booking_write_tool" in node.module
            )
        ):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.10 A55 forbidden list: 'recording an unverified booking'
    — this module holds no write tool or GraphWriter of any kind, so
    there is no path back into the graph at all, verified or not."""

    def test_module_has_no_tool_or_write_import(self) -> None:
        assert not _references_any_tool_or_graph_write_machinery(confirmation_verifier_agent)

    def test_verification_module_also_has_no_tool_import(self) -> None:
        from app.agents.concierge import verification

        assert not _references_any_tool_or_graph_write_machinery(verification)


def test_agent_id_is_a55() -> None:
    assert str(AGENT_ID) == "A55"

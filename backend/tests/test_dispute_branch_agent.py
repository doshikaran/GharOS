"""Tests for A32 Dispute Branch Agent (`app.agents.ledger.dispute_branch_agent`).

PHASES.md Gate 7's own acceptance list: "SMS/ledger mismatch -> dispute
branch, no auto-resolution." The single most important test in this file
is `TestNeverChoosesStructurally` — the literal, testable "never chooses"
forbidden-list item (spec §15.7 A32): the output type itself must not be
able to express a chosen/resolved figure, not merely go untested for it.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import NodeId

from app.agents.ledger.dispute_branch_agent import AGENT_ID, DisputeBranchAgent
from app.agents.ledger.types import ConflictingFigure, DisputePresentation
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _agent(response_obj: dict[str, object]) -> DisputeBranchAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return DisputeBranchAgent(gemini_client=client)


def _figure(source: str, amount: float, event_id: str) -> ConflictingFigure:
    return ConflictingFigure(
        source_label=source,
        amount=amount,
        currency="INR",
        reported_at=_NOW,
        evidence_event_id=NodeId(event_id),
        evidence_text=f"{source} reported {amount:.2f}",
    )


class TestNeverChoosesStructurally:
    """The forbidden-list item made literal: no field on `DisputePresentation`
    (or `ConflictingFigure`) can hold a single chosen/resolved figure —
    checked directly against the dataclass's own field set, not by
    convention."""

    _FORBIDDEN_FIELD_HINTS = {
        "resolved_amount",
        "correct_figure",
        "correct_amount",
        "resolution",
        "verdict",
        "winner",
        "chosen_figure",
        "final_amount",
    }

    def test_dispute_presentation_has_no_resolution_field(self) -> None:
        field_names = set(DisputePresentation.__dataclass_fields__.keys())
        assert field_names.isdisjoint(self._FORBIDDEN_FIELD_HINTS)
        # And the fields it DOES have are exactly the neutral, symmetric shape:
        assert field_names == {
            "subject",
            "figure_a",
            "figure_b",
            "discrepancy_amount",
            "context",
            "confidence",
            "escalated_to",
        }

    def test_escalated_to_is_pinned_to_the_single_human_resolution_value(self) -> None:
        field = DisputePresentation.__dataclass_fields__["escalated_to"]
        assert field.default == "human_resolution"

    def test_conflicting_figure_has_no_correctness_field(self) -> None:
        field_names = set(ConflictingFigure.__dataclass_fields__.keys())
        assert field_names.isdisjoint(self._FORBIDDEN_FIELD_HINTS | {"is_correct", "verified"})


class TestPresentBothFigures:
    def test_both_figures_present_with_evidence_neither_favoured(self) -> None:
        agent = _agent(
            {
                "context": (
                    "The SMS confirmation and the recorded ledger debit disagree on the maintenance "
                    "amount for August; the difference may be a partial payment or a delayed SMS."
                ),
                "confidence": 0.7,
            }
        )
        sms_figure = _figure("SMS notification", 2600.0, "sms-1")
        ledger_figure = _figure("ledger record", 2500.0, "ledger-1")

        presentation = agent.present(
            subject="August society maintenance debit", figure_a=sms_figure, figure_b=ledger_figure
        )

        assert presentation.figure_a == sms_figure
        assert presentation.figure_b == ledger_figure
        assert presentation.discrepancy_amount == 100.0
        assert presentation.escalated_to == "human_resolution"
        # neutral language check: the drafted context must not assert either source is right
        lowered = presentation.context.lower()
        assert "correct" not in lowered
        assert "right" not in lowered.split()  # avoid false-positive on words containing "right"

    def test_discrepancy_amount_is_computed_deterministically_not_by_the_model(self) -> None:
        """Even if the model's `context` text were to (wrongly) mention a
        number, `discrepancy_amount` itself is always this module's own
        arithmetic over the real input figures — proven by using a fake
        response that never mentions any number at all."""
        agent = _agent({"context": "these two records disagree", "confidence": 0.5})
        figure_a = _figure("SMS notification", 9200.0, "sms-1")
        figure_b = _figure("recorded SALARY payment", 8500.0, "ledger-salary-1")

        presentation = agent.present(
            subject="Maya's August salary payment", figure_a=figure_a, figure_b=figure_b
        )

        assert presentation.discrepancy_amount == 700.0

    def test_figures_presented_in_the_same_order_given(self) -> None:
        agent = _agent({"context": "n/a", "confidence": 0.5})
        figure_a = _figure("recorded", 9000.0, "e1")
        figure_b = _figure("computed", 8500.0, "e2")

        presentation = agent.present(subject="x", figure_a=figure_a, figure_b=figure_b)

        assert presentation.figure_a.source_label == "recorded"
        assert presentation.figure_b.source_label == "computed"


def test_agent_id_is_a32() -> None:
    assert str(AGENT_ID) == "A32"

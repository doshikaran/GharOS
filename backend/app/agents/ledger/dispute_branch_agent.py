"""A32 — Dispute Branch Agent (spec §10.6, §15.7).

*Responsibility:* assemble both conflicting figures with their evidence
for human resolution, whenever A28 (Reconciliation) flags an SMS-vs-ledger
or salary mismatch (`ReconciliationFinding.requires_dispute_branch`).

*Model tier:* Pro-tier — writing a genuinely neutral narrative summary of
a disagreement (naming both figures fairly, without the phrasing itself
tipping a reader toward one side) is real judgment, not string
interpolation. **The two figures and the discrepancy amount are always
computed deterministically by this module from the caller's input, never
by the model** — the model's only job is the `context` prose; it cannot
smuggle a "correct" figure into `DisputePresentation` even through biased
language, because the output type has nowhere to put one (see below).

*Forbidden:* **choosing which is correct.** This is enforced by the type
system, not by convention: `types.DisputePresentation` has no
`resolved_amount`/`correct_figure`/verdict field anywhere in its
definition — there is no way to construct an instance that expresses a
chosen figure without editing that frozen dataclass. `escalated_to` is
pinned to the single literal value `"human_resolution"`. This module's own
`present()` method never receives or infers "which one is right" from
anywhere; it always presents `figure_a` and `figure_b` in the same
input order it was given them.
"""

from __future__ import annotations

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_str
from .types import ConflictingFigure, DisputePresentation

AGENT_ID = AgentId("A32")

logger = structlog.get_logger(__name__)


class DisputeBranchAgent:
    """A32 Dispute Branch. Dependency-injected on a `GeminiClient` only —
    no tool of any kind; there is nothing this agent could legitimately
    act on (it presents, it never resolves)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def present(
        self, *, subject: str, figure_a: ConflictingFigure, figure_b: ConflictingFigure
    ) -> DisputePresentation:
        """Assembles a neutral, evidence-linked presentation of two
        conflicting figures.

        Args:
            subject: what's in dispute, e.g. "August society maintenance
                debit".
            figure_a: the first independently-sourced figure.
            figure_b: the second independently-sourced figure.

        Returns:
            A `DisputePresentation` — see this module's docstring for why
            it structurally cannot express a chosen figure.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape.
        """
        discrepancy_amount = abs(figure_a.amount - figure_b.amount)

        prompt = load_prompt("A32")
        rendered = prompt.text.format(
            subject=subject,
            figure_a_source=figure_a.source_label,
            figure_a_amount=f"{figure_a.amount:.2f}",
            figure_a_currency=figure_a.currency,
            figure_a_reported_at=figure_a.reported_at.isoformat(),
            figure_a_evidence=figure_a.evidence_text,
            figure_b_source=figure_b.source_label,
            figure_b_amount=f"{figure_b.amount:.2f}",
            figure_b_currency=figure_b.currency,
            figure_b_reported_at=figure_b.reported_at.isoformat(),
            figure_b_evidence=figure_b.evidence_text,
            discrepancy_amount=f"{discrepancy_amount:.2f}",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        context = require_str(parsed, "context", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        logger.info(
            "agents.ledger.a32.completed",
            subject=subject,
            discrepancy_amount=discrepancy_amount,
        )
        return DisputePresentation(
            subject=subject,
            figure_a=figure_a,
            figure_b=figure_b,
            discrepancy_amount=discrepancy_amount,
            context=context,
            confidence=confidence,
        )


__all__ = ["AGENT_ID", "DisputeBranchAgent"]

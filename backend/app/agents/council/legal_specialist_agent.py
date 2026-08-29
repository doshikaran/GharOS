"""A46 — Legal/Compliance Specialist (spec §12.3 Phase 1, §12.5, §15.9,
PHASES.md Phase 12, ADR-019) — E2's `backend/app/agents/council/`.

*Responsibility:* documentation, society rules, regulatory requirements
(spec §12.5, §15.9). Reports a real position; never eliminates a branch
(that is A43 Care's own, exclusive job this phase — see
`types.SpecialistPosition`'s own docstring).

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — real judgment
over a real household's own legal/regulatory documentation, not a lookup.

**Scoped-reader discipline (ADR-019 Decision 1, structurally enforced —
see `backend/tests/test_council_specialist_scope_boundaries.py`):** this
module's constructor accepts **only**
`app.graph.scoped_reader.ScopedGraphReader` — never
`contracts.repositories.GraphReader` — and imports no other graph-access
type at all. `LEGAL_SCOPE` (`Constraint` where `kind in {LEGAL, CUSTODY}`;
`SourceDocument`) is the only scope this class is ever constructed with in
this codebase's own pipeline (`pipeline.py`).

**Phase-1 isolation (structural — spec §12.3 Phase 1, Gate 12):**
`report()`'s only parameter is `types.SpecialistReportRequest`, which
carries `framing` alone — no field anywhere through which another
specialist's or delegate's output could reach this call.

*Forbidden:* **giving legal advice** — flags issues for professional
review only (enforced by prompt instruction, checked by
`backend/tests/test_legal_specialist_agent.py`'s own text-pattern
assertion that this module's prompt explicitly instructs against it —
this module holds no tool of any kind that could constitute "advice" as
an action, only a reported position). **Eliminating a branch** —
`eliminated_branch_ids` is hardcoded to `()` in `report()`'s own
construction code below, never sourced from the model's response at all.
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...graph.scoped_reader import ScopedGraphReader
from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from . import context
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_stance, require_str, require_str_tuple
from .types import SpecialistPosition, SpecialistReportRequest

AGENT_ID = AgentId("A46")


class LegalSpecialistAgent:
    """A46 Legal/Compliance Specialist. Dependency-injected on a
    `GeminiClient` and **exactly one** `ScopedGraphReader` — no other
    graph access, no write tool (this specialist only reports)."""

    def __init__(self, *, gemini_client: GeminiClient, scoped_reader: ScopedGraphReader) -> None:
        self._gemini_client = gemini_client
        self._scoped_reader = scoped_reader

    def report(self, request: SpecialistReportRequest) -> SpecialistPosition:
        """Reports Legal's real, isolated position on `request.framing`.

        Args:
            request: the decision's basic framing alone — no sibling
                specialist or delegate data reaches this call.

        Returns:
            A `SpecialistPosition` for `AgentId("A46")`.
            `eliminated_branch_ids` is always `()`.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, or named a stance
                outside `{"supports", "opposes", "neutral"}`.
        """
        framing = request.framing
        related_nodes = context.resolve_scoped_related_nodes(self._scoped_reader, framing=framing)
        evidence_summaries = context.summarize_scoped_nodes(related_nodes)
        evidence_block = (
            "\n".join(f"- {summary}" for summary in evidence_summaries)
            if evidence_summaries
            else (
                "(no real legal/custody Constraint or SourceDocument data was found "
                "for this decision's real anchors)"
            )
        )

        prompt = load_prompt("A46")
        rendered = prompt.text.format(
            question=framing.question,
            trigger=framing.trigger,
            branches_block=context.branches_block(framing),
            legal_evidence_block=evidence_block,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        stance = require_stance(parsed, "stance", agent_id=AGENT_ID)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        if not reasoning.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="reasoning must not be blank", raw_text=call_result.text
            )
        evidence_refs = require_str_tuple(parsed, "evidence_refs", agent_id=AGENT_ID)

        return SpecialistPosition(
            agent_id=str(AGENT_ID),
            stance=stance,
            reasoning=reasoning,
            evidence_refs=evidence_refs,
            eliminated_branch_ids=(),
        )


__all__ = ["AGENT_ID", "LegalSpecialistAgent"]

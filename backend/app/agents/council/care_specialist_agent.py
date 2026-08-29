"""A43 — Care Specialist (spec §12.3 Phase 1-2, §12.4, §15.9,
PHASES.md Phase 12, ADR-019) — E2's `backend/app/agents/council/`.

*Responsibility:* queries **only** the constraint/medical subgraph —
mobility, access, proximity, care continuity (spec §12.4: "Dad's mobility
constraint sets minimum door height and maximum seat height. **Hard
constraint — eliminates options.**"). This is the **one** specialist in
this package whose `SpecialistPosition.eliminated_branch_ids` can ever be
non-empty (Gate 12: "Care's hard constraint ELIMINATES options, does not
score them down") — see `types.SpecialistPosition`'s own docstring and
`backend/tests/test_care_specialist_elimination.py` for the fixture proof.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — whether a
real household mobility/medical constraint physically rules out a real
candidate option is genuine judgment, never a lookup.

**Scoped-reader discipline (ADR-019 Decision 1, structurally enforced —
see `backend/tests/test_council_specialist_scope_boundaries.py`):** this
module's constructor accepts **only**
`app.graph.scoped_reader.ScopedGraphReader` — never
`contracts.repositories.GraphReader` — and imports no other graph-access
type at all. `CARE_SCOPE` (`Constraint` where `kind in {MEDICAL,
MOBILITY}`; `Person`, capability flags only — this module reads no
`Person` field beyond `has_medical_proxy`/mobility-relevant ones, honouring
ADR-019's "node-level scoping cannot redact individual fields" caveat in
code, not just in the scope's own docstring) is the only scope this class
is ever constructed with in this codebase's own pipeline (`pipeline.py`).

**Phase-1 isolation (structural — spec §12.3 Phase 1, Gate 12):**
`report()`'s only parameter is `types.SpecialistReportRequest`, which
carries `framing` alone — no field anywhere through which another
specialist's or delegate's output could reach this call.

**Elimination is real-data-gated, not model-say-so-gated:** the model is
only ever *asked* about elimination when this module's own code has
already found at least one real `HARD`-severity `Constraint` (kind
MEDICAL/MOBILITY) among its resolved, in-scope nodes (`_hard_constraints`
below) — a household with no such constraint on file never even receives
an elimination-shaped prompt, so `eliminated_branch_ids` is empty by
construction in that case, not merely because the model declined to name
anything. When a hard constraint IS present, every eliminated branch id
the model names is additionally validated against the real candidate
branch id set before being accepted — an invented id is a malformed
response, never silently accepted.
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Constraint, ConstraintSeverity, NodeId

from ...graph.scoped_reader import ScopedGraphReader
from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from . import context
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_list, require_stance, require_str, require_str_tuple
from .types import DecisionFraming, SpecialistPosition, SpecialistReportRequest

AGENT_ID = AgentId("A43")


def _hard_constraints(nodes: tuple[object, ...]) -> tuple[Constraint, ...]:
    """The real, code-checked gate for whether elimination reasoning even
    runs — never inferred from the model's own say-so."""
    return tuple(
        node for node in nodes if isinstance(node, Constraint) and node.severity == ConstraintSeverity.HARD
    )


def _hard_constraints_block(hard_constraints: tuple[Constraint, ...]) -> str:
    return "\n".join(
        f"- Constraint(kind={c.kind.value}, \"{c.original_text}\", structured={c.structured})"
        for c in hard_constraints
    )


class CareSpecialistAgent:
    """A43 Care Specialist. Dependency-injected on a `GeminiClient` and
    **exactly one** `ScopedGraphReader` — no other graph access, no write
    tool (this specialist only reports; A49 Recorder owns persistence)."""

    def __init__(self, *, gemini_client: GeminiClient, scoped_reader: ScopedGraphReader) -> None:
        self._gemini_client = gemini_client
        self._scoped_reader = scoped_reader

    def report(self, request: SpecialistReportRequest) -> SpecialistPosition:
        """Reports Care's real, isolated position on `request.framing`,
        eliminating any real candidate branch a genuine HARD mobility/
        medical constraint rules out.

        Args:
            request: the decision's basic framing alone — no sibling
                specialist or delegate data reaches this call.

        Returns:
            A `SpecialistPosition` for `AgentId("A43")`.
            `eliminated_branch_ids` is non-empty only when a real HARD
            constraint was found in scope AND the model named at least one
            real candidate branch it rules out.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, named a stance outside
                `{"supports", "opposes", "neutral"}`, or named an
                eliminated branch id outside the real candidate set.
        """
        framing = request.framing
        related_nodes = context.resolve_scoped_related_nodes(self._scoped_reader, framing=framing)
        hard_constraints = _hard_constraints(related_nodes)
        evidence_summaries = context.summarize_scoped_nodes(related_nodes)
        evidence_block = (
            "\n".join(f"- {summary}" for summary in evidence_summaries)
            if evidence_summaries
            else (
                "(no real medical/mobility Constraint or Person capability data was found "
                "for this decision's real anchors)"
            )
        )

        prompt = load_prompt("A43")
        rendered = prompt.text.format(
            question=framing.question,
            trigger=framing.trigger,
            branches_block=context.branches_block(framing),
            care_evidence_block=evidence_block,
            hard_constraints_block=(
                _hard_constraints_block(hard_constraints)
                if hard_constraints
                else "(no HARD-severity medical/mobility constraint is on file — do not eliminate anything)"
            ),
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
        eliminated_branch_ids = self._validated_eliminations(
            parsed,
            framing=framing,
            hard_constraints_present=bool(hard_constraints),
            raw_text=call_result.text,
        )

        return SpecialistPosition(
            agent_id=str(AGENT_ID),
            stance=stance,
            reasoning=reasoning,
            evidence_refs=evidence_refs,
            eliminated_branch_ids=eliminated_branch_ids,
        )

    def _validated_eliminations(
        self,
        parsed: dict[str, object],
        *,
        framing: DecisionFraming,
        hard_constraints_present: bool,
        raw_text: str,
    ) -> tuple[NodeId, ...]:
        raw_eliminations = require_list(parsed, "hard_eliminations", agent_id=AGENT_ID)
        if not raw_eliminations:
            return ()
        if not hard_constraints_present:
            # The model volunteered an elimination with no real HARD
            # constraint backing it in this specialist's own scope — a
            # malformed response, never silently honoured (this is the
            # real, code-level gate the module docstring describes).
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason="hard_eliminations was non-empty but no real HARD constraint was found in scope",
                raw_text=raw_text,
            )
        real_branch_ids = {branch.branch_id for branch in framing.candidate_branches}
        eliminated: list[NodeId] = []
        for entry in raw_eliminations:
            if not isinstance(entry, dict) or not isinstance(entry.get("branch_id"), str):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"hard_eliminations entry {entry!r} is not a {{'branch_id': str, ...}} object",
                    raw_text=raw_text,
                )
            branch_id = entry["branch_id"]
            if branch_id not in {str(bid) for bid in real_branch_ids}:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"hard_eliminations names {branch_id!r}, not a real candidate branch id",
                    raw_text=raw_text,
                )
            matching = next(bid for bid in real_branch_ids if str(bid) == branch_id)
            if matching not in eliminated:
                eliminated.append(matching)
        return tuple(eliminated)


__all__ = ["AGENT_ID", "CareSpecialistAgent"]

"""A48 — Council Adversary (spec §12.3 Phase 5, §12.4, §15.9,
PHASES.md Phase 12, ADR-019 Decision 7) — E2's
`backend/app/agents/council/`.

*Responsibility:* attacks the **arbiter's already-resolved** winning
branch using the household's own real `OUTCOME` history (spec §12.4:
"your household has historically underestimated maintenance by 40% —
here are the three OUTCOME records..."). Runs *after*
`app.solvers.council_arbiter.resolve()` (ADR-019 Decision 7: there is no
earlier, separate "leading option" concept anywhere in this protocol, and
design rule 2 forbids any agent's LLM output from feeding back into the
deterministic arbiter's own math) — this module holds no path back into
`council_arbiter` at all (no import of it).

*Model tier:* Pro-tier, elevated thinking (`model_router.
PRO_TIER_ALLOWLIST`) — genuinely critiquing a real option against a real
household's own history is adversarial, multi-step reasoning.

**Not subgraph-restricted — deliberately holds an unscoped `GraphReader`**
(spec's own design: the Adversary needs household-wide history access to
do its job, unlike the domain specialists' own T0 subgraph scoping).

**Real citations only, never a generic risk template (spec §15.9 A48):**
`AdversaryAttack.cited_outcome_ids` is built exclusively from
`GraphReader.outcome_variance(category_tag)`/`GraphReader.history
(winning_branch_id)`'s own real results — the model is never asked to
name an outcome id itself; it is only asked to reason over the real
outcomes this module already fetched and to select/reference specific
ones by an index this module controls (`_build_evidence_block`), which
this module then maps back to the real ids. **When real history is
genuinely empty** (a fixture with zero matching outcomes, or a household
new enough to have none on file), no Gemini call is made at all and the
returned `critique` states the honest "no historical precedent found"
fact directly — never a fabricated citation, and never a generic
risk-template critique standing in for real evidence (same "say so, never
invent" discipline as Phase 11's A36/A39).

*Forbidden:* **proposing alternatives** — `types.AdversaryAttack` has no
field for a counter-option at all (see that dataclass's own docstring);
this module's prompt does not ask for one either.
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId, Outcome
from contracts.repositories import GraphReader

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from . import context
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_list, require_str
from .types import AdversaryAttack, AdversaryAttackRequest

AGENT_ID = AgentId("A48")

_THINKING_BUDGET = 8000
"""This agent's own justified elevated-thinking budget (never inherited
from another agent's constant) — genuinely critiquing a resolved option
against a real household's own historical variance is adversarial,
multi-step reasoning, not a single lookup."""

_NO_PRECEDENT_CRITIQUE = (
    "No historical precedent was found in this household's own OUTCOME records for this "
    "decision category or for this specific branch — this attack cannot be grounded in real "
    "household history, so none is claimed. (Honest absence of evidence, not evidence of safety.)"
)


def _dedupe_outcomes(*outcome_groups: tuple[Outcome, ...]) -> tuple[Outcome, ...]:
    seen: set[NodeId] = set()
    deduped: list[Outcome] = []
    for group in outcome_groups:
        for outcome in group:
            if outcome.id in seen:
                continue
            seen.add(outcome.id)
            deduped.append(outcome)
    return tuple(deduped)


def _evidence_block(outcomes: tuple[Outcome, ...]) -> str:
    lines = []
    for index, outcome in enumerate(outcomes):
        variance = f"{outcome.variance:+.4g}" if outcome.variance is not None else "unknown"
        lines.append(
            f"[{index}] id={outcome.id} predicted={outcome.predicted!r} actual={outcome.actual!r} "
            f"variance={variance} tags={list(outcome.attribution_tags)}"
        )
    return "\n".join(lines)


class CouncilAdversaryAgent:
    """A48 Council Adversary. Dependency-injected on a `GeminiClient` and
    an unscoped `GraphReader` (T0-equivalent, household-wide — this is the
    one Council agent this phase deliberately does not subgraph-restrict);
    holds no write tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient, graph_reader: GraphReader) -> None:
        self._gemini_client = gemini_client
        self._graph_reader = graph_reader

    def attack(self, request: AdversaryAttackRequest) -> AdversaryAttack:
        """Attacks `request.winning_branch_id` using this household's own
        real `OUTCOME` history.

        Args:
            request: the decision's basic framing, the arbiter's already-
                resolved winning branch id, and the real decision-category
                tag to check history against.

        Returns:
            An `AdversaryAttack`. `cited_outcome_ids` is non-empty
            whenever real matching history exists; empty, paired with an
            honest "no historical precedent found" `critique`, only when
            it genuinely does not.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, referenced an evidence
                index outside the real fetched set, or `critique` was
                blank.
        """
        category_outcomes = self._graph_reader.outcome_variance(request.category_tag)
        branch_outcomes = self._graph_reader.history(request.winning_branch_id)
        real_outcomes = _dedupe_outcomes(category_outcomes, branch_outcomes)

        if not real_outcomes:
            return AdversaryAttack(
                target_branch_id=request.winning_branch_id,
                critique=_NO_PRECEDENT_CRITIQUE,
                cited_outcome_ids=(),
            )

        winning_label = next(
            (b.label for b in request.framing.candidate_branches if b.branch_id == request.winning_branch_id),
            str(request.winning_branch_id),
        )
        prompt = load_prompt("A48")
        rendered = prompt.text.format(
            question=request.framing.question,
            winning_branch_label=winning_label,
            branches_block=context.branches_block(request.framing),
            evidence_block=_evidence_block(real_outcomes),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered, thinking_budget=_THINKING_BUDGET
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        critique = require_str(parsed, "critique", agent_id=AGENT_ID)
        if not critique.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="critique must not be blank", raw_text=call_result.text
            )

        raw_indices = require_list(parsed, "cited_evidence_indices", agent_id=AGENT_ID)
        cited_outcome_ids: list[NodeId] = []
        for raw_index in raw_indices:
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"cited_evidence_indices contains {raw_index!r}, not a real evidence index",
                    raw_text=call_result.text,
                )
            if not (0 <= raw_index < len(real_outcomes)):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"cited_evidence_indices contains {raw_index!r}, not a real evidence index",
                    raw_text=call_result.text,
                )
            outcome_id = real_outcomes[raw_index].id
            if outcome_id not in cited_outcome_ids:
                cited_outcome_ids.append(outcome_id)

        if not cited_outcome_ids:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason="real history was available but cited_evidence_indices was empty",
                raw_text=call_result.text,
            )

        return AdversaryAttack(
            target_branch_id=request.winning_branch_id,
            critique=critique,
            cited_outcome_ids=tuple(cited_outcome_ids),
        )


__all__ = ["AGENT_ID", "CouncilAdversaryAgent"]

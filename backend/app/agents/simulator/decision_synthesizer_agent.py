"""A40 — Decision Synthesizer (spec §11.3, §15.8, PHASES.md Phase 11,
ADR-017) — E2's `backend/app/agents/simulator/`.

*Responsibility:* assemble the final trade-off brief from a real
`Decision` and its real `Branch`es (each already carrying A37's
projections and A38's critiques on its own `critiques` tuple, fetched via
`app.graph.decision_repository.FirestoreDecisionRepository.branches_for`
by the caller — this module holds no `GraphReader` of its own, per this
package's established "pre-resolved by the caller" precedent), plus
A39's real calibration evidence. Also supports interrogation mode
(`answer_followup`) and backward mode's failure-point narration
(`synthesize_backward`, ADR-017 decision 3 — a second entry point on this
same agent, not a seventh).

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) for all three
entry points — assembling a trade-off brief without collapsing it into a
verdict, answering a household's question grounded only in the brief's
own content, and narrating a predicted failure point from real variance
evidence are each genuine judgment calls, never a lookup.

*Forbidden:* **recommending a choice on emotionally-loaded family
decisions.** `types.DecisionBrief`/`types.BackwardModeAnalysis` have no
verdict-shaped field at all — structurally impossible to represent a
recommendation (see `test_decision_synthesizer_agent.py::
TestNoVerdictField`). As defence in depth against a model smuggling
verdict-shaped *prose* into a field that does exist (`trade_offs`,
`branch_summaries`, an `answer_followup` response, `suggested_
mitigations`), `_VERDICT_PHRASES` is a deterministic keyword backstop
(mirrors `grounding_research_agent._REJECTED_PROJECTION_PHRASES`'s
identical role one phase earlier in this same package) — a hit raises
`errors.VerdictLeaked` and rejects the whole response, never silently
stripped.

`answer_followup` never makes a new tool/search call — it is grounded
only in the already-produced `DecisionBrief`'s own content, per spec
§11.4's interrogation-mode contract.
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Branch, Decision, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.calibration_stats import RankedOutcome
from .errors import ModelResponseMalformed, VerdictLeaked
from .json_utils import parse_json_response, require_dict, require_str, require_str_tuple
from .types import BackwardModeAnalysis, BackwardSynthesisRequest, CalibrationNarration, DecisionBrief

AGENT_ID = AgentId("A40")

_VERDICT_PHRASES: tuple[str, ...] = (
    "we recommend",
    "i recommend",
    "my recommendation",
    "our recommendation",
    "the recommended",
    "the best option is",
    "the best choice is",
    "you should choose",
    "you should pick",
    "you should go with",
    "you should select",
)
"""Deterministic backstop against a verdict smuggled into otherwise
trade-off-shaped prose — spec §15.8 A40's forbidden behaviour
("recommending a choice on emotionally-loaded family decisions") must not
depend on the model's own restraint alone. A hit rejects the whole
response rather than silently stripping the offending phrase (never
reinterpreting a malformed response as a best-guess success)."""


def _reject_if_verdict_leaked(*, field: str, values: tuple[str, ...], raw_text: str) -> None:
    for value in values:
        lowered = value.lower()
        for phrase in _VERDICT_PHRASES:
            if phrase in lowered:
                raise VerdictLeaked(agent_id=AGENT_ID, field=field, matched_phrase=phrase, raw_text=raw_text)


def _branch_block(branch: Branch) -> str:
    impacts = (
        "\n".join(f"  - {category}: {claim}" for category, claim in branch.projected_impacts.items())
        if branch.projected_impacts
        else "  (no projected impacts on file)"
    )
    refs = "\n".join(f"  - {ref}" for ref in branch.grounding_refs) if branch.grounding_refs else "  (none)"
    critiques = (
        "\n".join(f"  - {critique}" for critique in branch.critiques)
        if branch.critiques
        else "  (no adversarial critique on file)"
    )
    return (
        f"### Branch: {branch.label}\nProjected impacts:\n{impacts}\nExternal sources:\n{refs}\n"
        f"Adversarial critique:\n{critiques}"
    )


def _branches_block(branches: tuple[Branch, ...]) -> str:
    return "\n\n".join(_branch_block(branch) for branch in branches)


def _calibration_block(calibrations: tuple[CalibrationNarration, ...]) -> str:
    if not calibrations:
        return "(no calibration evidence was supplied for this decision)"
    return "\n".join(f"- [{c.tag}] {c.narrative}" for c in calibrations)


def _list_block(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "(none)"


class DecisionSynthesizerAgent:
    """A40 Decision Synthesizer. Dependency-injected on a `GeminiClient`
    only — every `Decision`/`Branch`/`CalibrationNarration` this agent
    reasons over is pre-resolved and handed in by the caller; this module
    holds no `GraphReader`, no `GraphWriter`, no tool of any kind (it
    produces a brief, it does not persist one — `Decision`/`Branch` are
    already the durable record)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def synthesize(
        self,
        *,
        decision: Decision,
        branches: tuple[Branch, ...],
        calibrations: tuple[CalibrationNarration, ...] = (),
    ) -> DecisionBrief:
        """Assembles the forward-mode `DecisionBrief`.

        Args:
            decision: the real `Decision` node (A35's output).
            branches: this decision's real `Branch`es, typically
                `FirestoreDecisionRepository.branches_for(decision.id)` —
                each already carrying A37's projections and A38's
                critiques on its own `critiques` tuple. Must be non-empty.
            calibrations: zero or more real `CalibrationNarration`s (A39)
                offered as context — never used to favour one branch.

        Returns:
            A `DecisionBrief`. `branch_summaries` has exactly one entry
            per `branches` label, in `branches`' own order.

        Raises:
            ValueError: `branches` is empty — there is no brief to
                assemble for a decision with no branches on file.
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or
                `branch_summaries`' keys did not exactly match the real
                branch labels given.
            errors.VerdictLeaked: the response smuggled verdict-shaped
                language into `branch_summaries`, `trade_offs`, or
                `open_questions`.
        """
        if not branches:
            raise ValueError("cannot synthesize a DecisionBrief for a Decision with no branches on file")

        prompt = load_prompt("A40")
        rendered = prompt.text.format(
            decision_question=decision.question,
            decision_trigger=decision.trigger,
            branches_block=_branches_block(branches),
            calibration_block=_calibration_block(calibrations),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        raw_summaries = require_dict(parsed, "branch_summaries", agent_id=AGENT_ID)
        real_labels = [branch.label for branch in branches]
        _validate_summary_keys(real_labels, raw_summaries, raw_text=call_result.text)
        branch_summaries = tuple(
            f"{label}: {require_str(raw_summaries, label, agent_id=AGENT_ID)}" for label in real_labels
        )

        trade_offs = require_str_tuple(parsed, "trade_offs", agent_id=AGENT_ID)
        open_questions = require_str_tuple(parsed, "open_questions", agent_id=AGENT_ID)

        _reject_if_verdict_leaked(
            field="branch_summaries", values=branch_summaries, raw_text=call_result.text
        )
        _reject_if_verdict_leaked(field="trade_offs", values=trade_offs, raw_text=call_result.text)
        _reject_if_verdict_leaked(
            field="open_questions", values=open_questions, raw_text=call_result.text
        )

        return DecisionBrief(
            decision_id=decision.id,
            branch_summaries=branch_summaries,
            trade_offs=trade_offs,
            open_questions=open_questions,
        )

    def answer_followup(self, brief: DecisionBrief, question: str) -> str:
        """Interrogation mode: answers `question` grounded only in
        `brief`'s own already-produced content — no new tool or search
        call of any kind (spec §11.4).

        Args:
            brief: the already-produced `DecisionBrief` to interrogate.
            question: the household's real free-text question.

        Returns:
            A plain-text answer.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or `answer` was
                blank.
            errors.VerdictLeaked: the answer smuggled verdict-shaped
                language.
        """
        prompt = load_prompt("A40_FOLLOWUP")
        rendered = prompt.text.format(
            branch_summaries_block=_list_block(brief.branch_summaries),
            trade_offs_block=_list_block(brief.trade_offs),
            open_questions_block=_list_block(brief.open_questions),
            question=question,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        answer = require_str(parsed, "answer", agent_id=AGENT_ID)
        if not answer.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="answer must not be blank", raw_text=call_result.text
            )
        _reject_if_verdict_leaked(field="answer", values=(answer,), raw_text=call_result.text)
        return answer

    def synthesize_backward(self, request: BackwardSynthesisRequest) -> BackwardModeAnalysis:
        """Backward mode (ADR-017 decision 3): narrates the predicted
        failure point for a committed plan, using A39's real ranked
        outcome evidence for the plan's category — never a generic claim.

        Args:
            request: A35's backward-mode `DecisionFrame`, A39's
                category-matched `CalibrationNarration`, and the real
                plan description text.

        Returns:
            A `BackwardModeAnalysis`. When `request.calibration.
            ranked_outcomes` is empty (no real settled-variance evidence
            for this category at all), this is a deterministic, honest
            "insufficient evidence" result — no model call, no invented
            failure point, `supporting_outcome_ids=()`.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, `assumed_failure_
                point` was blank, or `supporting_outcome_ids` named an id
                not present in `request.calibration.ranked_outcomes`.
            errors.VerdictLeaked: the response smuggled verdict-shaped
                language into `assumed_failure_point` or `suggested_
                mitigations`.
        """
        ranked_outcomes = request.calibration.ranked_outcomes
        if not ranked_outcomes:
            return BackwardModeAnalysis(
                plan_description=request.plan_description,
                assumed_failure_point=(
                    "no real past outcome with a settled variance exists for this category yet — "
                    "there is not enough household history to name a specific likely failure point."
                ),
                supporting_outcome_ids=(),
                confidence_note=request.calibration.estimate.note,
                suggested_mitigations=(),
            )

        prompt = load_prompt("A40_BACKWARD")
        rendered = prompt.text.format(
            plan_description=request.plan_description,
            calibration_narrative=request.calibration.narrative,
            ranked_outcomes_block=_ranked_outcomes_block(ranked_outcomes),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        assumed_failure_point = require_str(parsed, "assumed_failure_point", agent_id=AGENT_ID)
        if not assumed_failure_point.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="assumed_failure_point must not be blank", raw_text=call_result.text
            )
        supporting_outcome_ids = require_str_tuple(parsed, "supporting_outcome_ids", agent_id=AGENT_ID)
        real_ids = {str(ranked.outcome.id) for ranked in ranked_outcomes}
        for outcome_id in supporting_outcome_ids:
            if outcome_id not in real_ids:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"supporting_outcome_ids named {outcome_id!r}, not a real ranked outcome id",
                    raw_text=call_result.text,
                )
        if not supporting_outcome_ids:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason="assumed_failure_point named with no supporting_outcome_ids — never a generic claim",
                raw_text=call_result.text,
            )

        suggested_mitigations = require_str_tuple(parsed, "suggested_mitigations", agent_id=AGENT_ID)
        _reject_if_verdict_leaked(
            field="assumed_failure_point", values=(assumed_failure_point,), raw_text=call_result.text
        )
        _reject_if_verdict_leaked(
            field="suggested_mitigations", values=suggested_mitigations, raw_text=call_result.text
        )

        return BackwardModeAnalysis(
            plan_description=request.plan_description,
            assumed_failure_point=assumed_failure_point,
            supporting_outcome_ids=tuple(NodeId(outcome_id) for outcome_id in supporting_outcome_ids),
            confidence_note=request.calibration.narrative,
            suggested_mitigations=suggested_mitigations,
        )


def _validate_summary_keys(
    real_labels: list[str], raw_summaries: dict[str, object], *, raw_text: str
) -> None:
    given_keys = set(raw_summaries.keys())
    expected_keys = set(real_labels)
    if given_keys != expected_keys:
        raise ModelResponseMalformed(
            agent_id=AGENT_ID,
            reason=(
                f"branch_summaries keys {sorted(given_keys)} do not exactly match the real branch "
                f"labels {sorted(expected_keys)}"
            ),
            raw_text=raw_text,
        )


def _ranked_outcomes_block(ranked_outcomes: tuple[RankedOutcome, ...]) -> str:
    return "\n".join(
        f"- id={ranked.outcome.id}: predicted {ranked.outcome.predicted!r}, "
        f"actual {ranked.outcome.actual!r}, variance {ranked.outcome.variance:+.4g}"
        for ranked in ranked_outcomes
    )


__all__ = ["AGENT_ID", "DecisionSynthesizerAgent"]

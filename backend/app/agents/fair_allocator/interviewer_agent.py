"""A17 — Interviewer (spec §8.3 Stage 1, §15.8).

*Responsibility:* adaptive *comparative* elicitation — "would you rather
do two school runs or handle the plumber once?" — because humans compare
better than they rate (spec §8.3.1). This agent conducts the interview;
it never turns an answer into a number.

*Model tier:* Pro-tier for **question selection only**
(`select_next_comparison` — choosing which comparison teaches the
household the most, given every answer so far, is the genuine judgment
call: avoiding a pair whose answer is already implied by transitivity,
prioritising under-explored tasks). Flash for **parsing the human's real
answer** into a structured preference (`record_answer` — turning free
text into "preferred A / preferred B / tie" is routine normalisation,
matching A4 Message Normalization's own tier). Phrasing the chosen pair
as a natural comparative question (`phrase_question`) is plain string
templating, not reasoning — spec's own worked example ("would you rather
do two school runs or handle the plumber once?") is literally two task
descriptions filled into a fixed comparative frame, so this module makes
**no model call at all** for that step (cost discipline: an LLM call with
no real judgment behind it is waste, not flow).

*Forbidden:* **computing valuations or assigning.** This module has no
import of `app.solvers.fair_allocation` anywhere, never constructs a
`app.solvers.fair_allocation.CostMatrix`, and `types.ComparativePreference`
(this agent's entire output shape) has no field that could hold a cost
number or a task assignment — see that dataclass's own docstring for why
this is structural, not merely a convention this module happens to
follow.
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import ComparativePreference, ComparisonQuestion, NextComparisonRequest

AGENT_ID = AgentId("A17")

_VALID_PREFERENCES: frozenset[str] = frozenset({"task_a", "task_b", "tie"})


def _candidate_tasks_block(request: NextComparisonRequest) -> str:
    lines = [
        f'- id="{task_id}" description="{request.task_descriptions[str(task_id)]}"'
        for task_id in request.candidate_task_ids
    ]
    return "\n".join(lines) if lines else "(no candidate tasks remaining)"


def _already_asked_block(request: NextComparisonRequest) -> str:
    if not request.already_asked_pairs:
        return "(none yet)"
    return "\n".join(f"- {a} vs {b}" for a, b in request.already_asked_pairs)


def _preferences_block(request: NextComparisonRequest) -> str:
    if not request.preferences_so_far:
        return "(none yet)"
    lines = []
    for pref in request.preferences_so_far:
        if pref.preferred == "tie":
            lines.append(f"- {pref.task_a_id} and {pref.task_b_id} felt about the same")
        elif pref.preferred == "task_a":
            lines.append(f"- prefers {pref.task_a_id} over {pref.task_b_id}")
        else:
            lines.append(f"- prefers {pref.task_b_id} over {pref.task_a_id}")
    return "\n".join(lines)


def _pair_already_asked(request: NextComparisonRequest, task_a_id: NodeId, task_b_id: NodeId) -> bool:
    for a, b in request.already_asked_pairs:
        if {a, b} == {task_a_id, task_b_id}:
            return True
    return False


class InterviewerAgent:
    """A17 Interviewer. Dependency-injected on a `GeminiClient` only —
    deliberately no graph or solver dependency of any kind (see this
    module's docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def select_next_comparison(self, request: NextComparisonRequest) -> ComparisonQuestion | None:
        """Pro-tier: chooses the single most informative unasked pair to
        compare next.

        Args:
            request: the remaining candidate tasks, what has already been
                asked, and every preference collected so far this session.

        Returns:
            The chosen `ComparisonQuestion`, or `None` when the model
            judges no further comparison would teach anything new.

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape, or selected a task id
                not in `request.candidate_task_ids`, an identical pair, or
                a pair already asked this session.
        """
        prompt = load_prompt("A17")
        rendered = prompt.text.format(
            person_id=request.person_id,
            candidate_tasks_block=_candidate_tasks_block(request),
            already_asked_block=_already_asked_block(request),
            preferences_block=_preferences_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        done = require_bool(parsed, "done", agent_id=AGENT_ID, default=False)
        if done:
            return None

        task_a_id = NodeId(require_str(parsed, "task_a_id", agent_id=AGENT_ID))
        task_b_id = NodeId(require_str(parsed, "task_b_id", agent_id=AGENT_ID))
        rationale = require_str(parsed, "rationale", agent_id=AGENT_ID)

        candidate_set = set(request.candidate_task_ids)
        if task_a_id not in candidate_set or task_b_id not in candidate_set:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"selected task id(s) not among candidates: {task_a_id!r}, {task_b_id!r}",
                raw_text=call_result.text,
            )
        if task_a_id == task_b_id:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="selected the same task twice", raw_text=call_result.text
            )
        if _pair_already_asked(request, task_a_id, task_b_id):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"selected a pair already asked this session: {task_a_id!r}, {task_b_id!r}",
                raw_text=call_result.text,
            )

        return ComparisonQuestion(
            person_id=request.person_id,
            task_a_id=task_a_id,
            task_a_description=request.task_descriptions[str(task_a_id)],
            task_b_id=task_b_id,
            task_b_description=request.task_descriptions[str(task_b_id)],
            rationale=rationale,
        )

    def phrase_question(self, question: ComparisonQuestion) -> str:
        """Deterministic — no model call. Fills the chosen pair's real
        descriptions into a fixed comparative frame (spec §8.3.1's own
        worked example is exactly this shape)."""
        return f"Would you rather: (a) {question.task_a_description}, or (b) {question.task_b_description}?"

    def record_answer(self, *, question: ComparisonQuestion, raw_answer_text: str) -> ComparativePreference:
        """Flash: parses the person's real, free-text answer into a
        structured comparative preference.

        Args:
            question: the question this answer responds to.
            raw_answer_text: the person's real, unmodified answer text.

        Returns:
            A `ComparativePreference` — never a cost, never an assignment.

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape, or named a preference
                outside `_VALID_PREFERENCES`.
        """
        prompt = load_prompt("A17_ANSWER")
        rendered = prompt.text.format(
            task_a_description=question.task_a_description,
            task_b_description=question.task_b_description,
            raw_answer_text=raw_answer_text,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        preferred = require_str(parsed, "preferred", agent_id=AGENT_ID)
        if preferred not in _VALID_PREFERENCES:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason=f"unrecognised preference {preferred!r}", raw_text=call_result.text
            )
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)

        return ComparativePreference(
            person_id=question.person_id,
            task_a_id=question.task_a_id,
            task_b_id=question.task_b_id,
            preferred="task_a" if preferred == "task_a" else ("task_b" if preferred == "task_b" else "tie"),
            raw_answer_text=raw_answer_text,
            reasoning=reasoning,
            confidence=confidence,
        )


__all__ = ["AGENT_ID", "InterviewerAgent"]

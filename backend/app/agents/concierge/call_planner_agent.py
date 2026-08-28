"""A53 — Call Planner (spec §13.2 Step 4, §13.3, §15.10) — E2's half of
`backend/app/agents/concierge/`.

*Responsibility:* "pre-call brief: objective, authorised bounds,
disclosable facts, must-not-answer list" (spec §15.10 A53). Produces
`types.CallBrief` — the frozen handoff shape E3's A54 consumes — from
A52's top-ranked provider plus the household's real authorised bounds.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) per spec
§15.10's own roster entry — phrasing a natural, complete call objective
from a plain intent, a selected provider, and a set of preferred slots is
real judgment.

**Forbidden: setting bounds beyond what the human approved.** Structurally
enforced, not just prompted for: `plan()` below copies `date_range`,
`price_ceiling`, `preferred_slots`, and `fallback_acceptable` from
`types.CallPlanningRequest.authorized_bounds` onto the returned
`CallBrief` *verbatim* — there is no code path anywhere in this module
that reads any of those four fields out of the model's parsed JSON
response. The prompt asks the model for exactly two fields
(`objective`, `reasoning`); `_parse_json_response`'s result is never
consulted for anything bounds-shaped, so even a model response that
includes extra `price_ceiling`/`date_range`-looking keys (a prompt-
injection attempt, or simple confusion) has no field this code will ever
read them from — see `test_call_planner_agent.py`'s adversarial test for
the direct proof. `must_not_answer` is likewise built entirely
deterministically (`_must_not_answer_for`), from `CallPlanningRequest.
sensitive_topics` plus a fixed, code-owned per-category default list —
never touched by the model either.

This agent does not itself approve anything — Phase 5's existing
Approval Gate mechanism (E3's territory to invoke, before the call is
ever placed) is what authorises a `CallBrief` for use; this agent's only
job is producing one shaped so a human reviewing it can see the real,
complete bounds, not a summary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_str
from .types import CallBrief, CallPlanningRequest, CallPlanningResult

AGENT_ID = AgentId("A53")

_DEFAULT_MUST_NOT_ANSWER: tuple[str, ...] = (
    "medical diagnosis",
    "legal advice",
    "payment card or bank account details",
    "insurance claim adjudication",
)
_CATEGORY_MUST_NOT_ANSWER: dict[str, tuple[str, ...]] = {
    "dental": (
        "medical diagnosis",
        "treatment recommendation",
        "insurance claim adjudication",
        "payment card or bank account details",
    ),
}
"""Fixed, code-owned per-category defaults — never generated or expanded
by the model. `service_category` not present here falls back to
`_DEFAULT_MUST_NOT_ANSWER`."""


def _must_not_answer_for(service_category: str, extra: tuple[str, ...]) -> tuple[str, ...]:
    base = _CATEGORY_MUST_NOT_ANSWER.get(service_category, _DEFAULT_MUST_NOT_ANSWER)
    combined: list[str] = list(base)
    for topic in extra:
        if topic not in combined:
            combined.append(topic)
    return tuple(combined)


def _facts_block(facts: tuple[str, ...]) -> str:
    if not facts:
        return "(no facts authorised for disclosure on this call)"
    return "\n".join(f"- {fact}" for fact in facts)


def _slots_block(slots: tuple[datetime, ...]) -> str:
    if not slots:
        return "(no specific preferred slots — any slot within the date range is acceptable)"
    return "\n".join(f"{i + 1}. {slot.isoformat()}" for i, slot in enumerate(slots))


class CallPlannerAgent:
    """A53 Call Planner. Dependency-injected on a `GeminiClient` only —
    no approval-gate import, no voice/call tool import of any kind (this
    agent produces a `CallBrief`; it never places or authorises a
    call)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def plan(self, request: CallPlanningRequest) -> CallPlanningResult:
        """Produces a `CallBrief` for `request`'s target provider.

        Args:
            request: the target provider, person, and the household's
                real, already-approved bounds this call may not exceed.

        Returns:
            A `CallPlanningResult` whose `brief.date_range`,
            `brief.price_ceiling`, `brief.preferred_slots`, and
            `brief.fallback_acceptable` are always exactly
            `request.authorized_bounds`'s own values (see module
            docstring).

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or `objective` was
                blank.
        """
        bounds = request.authorized_bounds
        prompt = load_prompt("A53")
        rendered = prompt.text.format(
            target_provider_name=request.target_provider_name,
            person_display_name=request.person_display_name,
            service_category=request.service_category,
            objective_hint=request.objective_hint,
            disclosable_facts_block=_facts_block(request.disclosable_facts),
            date_range_block=f"{bounds.date_range[0].isoformat()} to {bounds.date_range[1].isoformat()}",
            price_ceiling_block=(
                f"{bounds.price_ceiling:.2f}"
                if bounds.price_ceiling is not None
                else "(no price ceiling — this call has no financial component)"
            ),
            preferred_slots_block=_slots_block(bounds.preferred_slots),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        objective = require_str(parsed, "objective", agent_id=AGENT_ID)
        if not objective.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="objective must not be blank", raw_text=call_result.text
            )
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        brief = CallBrief(
            target_provider_id=request.target_provider_id,
            person_id=request.person_id,
            objective=objective,
            date_range=bounds.date_range,
            price_ceiling=bounds.price_ceiling,
            disclosable_facts=request.disclosable_facts,
            must_not_answer=_must_not_answer_for(request.service_category, request.sensitive_topics),
            preferred_slots=bounds.preferred_slots,
            fallback_acceptable=bounds.fallback_acceptable,
        )

        return CallPlanningResult(
            brief=brief,
            objective_reasoning=reasoning,
            confidence=confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            planned_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "CallPlannerAgent"]

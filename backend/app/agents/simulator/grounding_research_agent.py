"""A36 — Grounding/Research (spec §11.3, §15.8, PHASES.md Phase 11,
ADR-017) — E2's `backend/app/agents/simulator/`.

*Responsibility:* pull real, citable external data for one branch of a
household decision, with real timestamps and an honest freshness note —
never a consequence claim (spec §15.8 A36 forbidden: "projecting
consequences" — that is A37's job, using this result as one input among
several).

*Model tier:* Flash for query construction (`_construct_query`) — turning
a topic into a good search string needs no hard judgment. The grounded
retrieval call itself
(`app.reasoning.gemini_client.GeminiClient.generate_grounded_text`) also
runs at the caller's requested tier (Flash by default here — retrieval is
not itself a judgment call). Pro-tier
(`model_router.PRO_TIER_ALLOWLIST`) only for `_filter_relevance` — judging
whether real, already-retrieved search results are actually relevant to
*this* branch's specific topic, and restating them neutrally.

**Honest empty case (ADR-017):** when the grounded call returns zero
citations, this agent makes no Pro-tier relevance call at all (nothing
real to filter) — `summary` states plainly that no external source was
found, `freshness_note` says there is nothing to assess freshness for.
Never invents a citation or a finding to fill the gap.

**Defence in depth against a projected consequence:** beyond the prompt's
own explicit instruction, `_REJECTED_PROJECTION_PHRASES` is a deterministic
keyword backstop (mirrors `app.agents.concierge.requirement_clarifier_
agent`'s urgency-keyword precedent) — if the model's own "neutral summary"
smuggles in consequence-projecting language anyway, the whole response is
rejected rather than silently passed through.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_str
from .types import GroundingRequest, GroundingResult

AGENT_ID = AgentId("A36")

_REJECTED_PROJECTION_PHRASES: tuple[str, ...] = (
    "this means",
    "this will",
    "you will need",
    "you should",
    "you will have to",
    "you can expect",
    "will affect you",
    "will cost you",
    "will impact",
)
"""Deterministic backstop against a consequence claim smuggled into a
"neutral" summary — spec §15.8 A36's forbidden behaviour
("projecting consequences") must not depend on the model's own restraint
alone. A hit here rejects the whole response rather than silently
stripping the offending phrase (never reinterpreting a malformed response
as a best-guess success)."""


def _reject_if_projects_consequences(*, summary: str, raw_text: str) -> None:
    lowered = summary.lower()
    for phrase in _REJECTED_PROJECTION_PHRASES:
        if phrase in lowered:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=(
                    f"summary contains consequence-projecting language ({phrase!r}) — A36 is "
                    "forbidden from projecting consequences, only reporting what sources say"
                ),
                raw_text=raw_text,
            )


class GroundingResearchAgent:
    """A36 Grounding/Research. Dependency-injected on a `GeminiClient`
    only — no `GraphReader`, no write tool of any kind. Every branch
    topic and household-context string this agent reasons over arrives
    pre-resolved on `types.GroundingRequest`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def research(self, request: GroundingRequest) -> GroundingResult:
        """Researches one branch's topic: constructs a real search query
        (Flash), retrieves real Google-Search-grounded results (Flash),
        and — only if grounding actually triggered — filters/restates
        them neutrally for relevance (Pro-tier).

        Args:
            request: the branch label, what to research, and real
                pre-resolved household context for relevance judgment.

        Returns:
            A `GroundingResult`. `citations` is empty exactly when
            grounding did not trigger for the constructed query — a real,
            expected, honestly-reported outcome.

        Raises:
            errors.ModelResponseMalformed: a model response could not be
                parsed as the expected JSON shape, or the relevance-
                filtering summary smuggled in consequence-projecting
                language.
        """
        search_query = self._construct_query(request)
        grounded = self._gemini_client.generate_grounded_text(
            agent_id=AGENT_ID,
            tier=ModelTier.FLASH,
            prompt=f"Research this and report factual findings with sources: {search_query}",
        )

        if not grounded.citations:
            now = datetime.now(UTC)
            return GroundingResult(
                branch_label=request.branch_label,
                citations=(),
                summary=(
                    f"No external source was found for '{request.topic}' (branch "
                    f"'{request.branch_label}') — Google Search grounding did not return "
                    "results for this query. This is a real, honest absence, not an error."
                ),
                freshness_note=(
                    f"Lookup attempted at {now.isoformat()} — no sources returned, so there is "
                    "nothing to assess freshness for."
                ),
            )

        summary, freshness_note = self._filter_relevance(request, raw_grounded_text=grounded.text)
        return GroundingResult(
            branch_label=request.branch_label,
            citations=grounded.citations,
            summary=summary,
            freshness_note=freshness_note,
        )

    def _construct_query(self, request: GroundingRequest) -> str:
        prompt = load_prompt("A36_QUERY")
        rendered = prompt.text.format(branch_label=request.branch_label, topic=request.topic)
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        query = require_str(parsed, "search_query", agent_id=AGENT_ID)
        if not query.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="search_query must not be blank", raw_text=call_result.text
            )
        return query

    def _filter_relevance(self, request: GroundingRequest, *, raw_grounded_text: str) -> tuple[str, str]:
        prompt = load_prompt("A36_RELEVANCE")
        rendered = prompt.text.format(
            branch_label=request.branch_label,
            topic=request.topic,
            household_context=request.household_context,
            raw_grounded_text=raw_grounded_text,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        summary = require_str(parsed, "summary", agent_id=AGENT_ID)
        freshness_note = require_str(parsed, "freshness_note", agent_id=AGENT_ID)
        _reject_if_projects_consequences(summary=summary, raw_text=call_result.text)
        return summary, freshness_note


__all__ = ["AGENT_ID", "GroundingResearchAgent"]

"""A50 — Requirement Clarifier (spec §13.2 Step 1, §15.10) — E2's half of
`backend/app/agents/concierge/`.

*Responsibility:* "graph-first, ask only the unknowable; urgency
detection" (spec §15.10 A50). The real graph-first check happens before
this agent ever runs — `context.resolve_known_facts` (called by whoever
assembles a `types.ClarificationRequest`) attempts a real resolution of
every requirement `context.SERVICE_CATEGORY_REQUIREMENTS[service_
category]` names, and only what a real query could not answer reaches
`ClarificationRequest.candidate_unknowns`. This agent then does two real
jobs over exactly those candidates:

1. Rank the genuinely unknown candidates by decision relevance and phrase
   a real question for the most relevant ones.
2. Detect urgency (pain/injury reported -> `UrgencyLevel.ELEVATED`,
   spec's own "the search prioritises earliest availability over
   rating").

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — spec §21.1
names this kind of graph-vs-request reasoning as a hard reasoning step,
and ranking genuinely-unknown facts by decision relevance is real
judgment, not lookup.

**Gate 10's literal, load-bearing checklist item: "'Book a dentist' asks
<=2 questions."** `MAX_CLARIFYING_QUESTIONS` below is a real, enforced
ceiling in this agent's own code — `clarify()` truncates
`questions` to this many *after* parsing the model's response, regardless
of how many the model proposed or how it ranked them. This is a
structural guarantee, not a prompted-for convention: even a model that
proposes ten questions, or refuses to rank them, can never produce more
than `MAX_CLARIFYING_QUESTIONS` questions in this agent's output. Every
candidate that does not make the cut is folded into `assumptions`
instead — accounted for, never silently dropped and never silently
turned into a third question.

*Forbidden:* **asking what the graph already knows.** Structurally
enforced, not just prompted for: `_parse_questions` rejects any proposed
question whose `targets_unknown` is not literally present in
`ClarificationRequest.candidate_unknowns` — a model cannot smuggle a
question about a graph-known fact back in, because it was never shown
that fact as an askable candidate in the first place (see the prompt's
own "Already known" section, which explicitly forbids asking about
anything listed there).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_list, require_str
from .types import ClarificationRequest, ClarificationResult, ClarifyingQuestion, UrgencyLevel

AGENT_ID = AgentId("A50")

MAX_CLARIFYING_QUESTIONS = 2
"""Gate 10's literal ceiling, made real code — see module docstring."""

_URGENCY_KEYWORDS: tuple[str, ...] = (
    "pain",
    "hurts",
    "hurting",
    "ache",
    "aches",
    "aching",
    "swollen",
    "swelling",
    "bleeding",
    "urgent",
    "asap",
    "emergency",
)
"""A deterministic backstop against a model that misses or downplays a
real, explicit urgency signal in the household's own words — spec §13.2
Step 1's "if pain is reported -> urgency escalates" is safety-adjacent
enough (a missed urgent dental/medical need directly affects scheduling
priority) that this agent never relies on the model's own restraint
alone for this one signal. A keyword hit here always escalates urgency
to `ELEVATED`, even overriding a model that classified the request as
`"routine"` — see `clarify()`'s own combination logic."""


def _keyword_detected_urgency(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _URGENCY_KEYWORDS)


def _known_facts_block(request: ClarificationRequest) -> str:
    if not request.known_facts:
        return "(nothing known yet from the household graph for this service category)"
    return "\n".join(f"- {fact.field}: {fact.value}" for fact in request.known_facts)


def _candidate_unknowns_block(request: ClarificationRequest) -> str:
    if not request.candidate_unknowns:
        return "(none — every requirement was already resolved from the graph)"
    return "\n".join(f"- {unknown}" for unknown in request.candidate_unknowns)


class RequirementClarifierAgent:
    """A50 Requirement Clarifier. Dependency-injected on a `GeminiClient`
    only — no `GraphReader`, no tool of any kind. Every graph fact this
    agent reasons over arrives pre-resolved on `types.
    ClarificationRequest` (this codebase's established "pre-resolved by
    the caller" precedent), via `context.resolve_known_facts`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def clarify(self, request: ClarificationRequest) -> ClarificationResult:
        """Decides which (if any) of the request's genuinely-unknown
        candidates are worth asking about, and detects urgency.

        Args:
            request: the household's request text plus every real,
                pre-resolved graph-known fact and genuinely-unknown
                candidate for this service category.

        Returns:
            A `ClarificationResult` — `questions` never longer than
            `MAX_CLARIFYING_QUESTIONS`.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, proposed a question
                targeting something outside `request.candidate_unknowns`,
                or named an urgency value outside `{routine, elevated}`.
        """
        prompt = load_prompt("A50")
        rendered = prompt.text.format(
            household_request_text=request.household_request_text,
            service_category=request.service_category,
            known_facts_block=_known_facts_block(request),
            candidate_unknowns_block=_candidate_unknowns_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        proposed_questions = self._parse_questions(parsed, request=request, raw_text=call_result.text)
        model_assumptions = tuple(
            item for item in require_list(parsed, "assumptions", agent_id=AGENT_ID) if isinstance(item, str)
        )

        urgency_raw = require_str(parsed, "urgency", agent_id=AGENT_ID)
        if urgency_raw not in ("routine", "elevated"):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason=f"unrecognised urgency {urgency_raw!r}", raw_text=call_result.text
            )
        model_urgency = UrgencyLevel(urgency_raw)
        urgency_reasoning = require_str(parsed, "urgency_reasoning", agent_id=AGENT_ID)

        keyword_elevated = _keyword_detected_urgency(request.household_request_text)
        final_urgency = (
            UrgencyLevel.ELEVATED
            if model_urgency is UrgencyLevel.ELEVATED or keyword_elevated
            else UrgencyLevel.ROUTINE
        )
        if keyword_elevated and model_urgency is not UrgencyLevel.ELEVATED:
            urgency_reasoning = (
                f"{urgency_reasoning} (escalated to elevated by automatic pain/urgency keyword "
                "detection in the household's own request text, overriding the model's routine "
                "classification — a real urgency signal is never silently missed)"
            )

        # The structural ceiling: never more than MAX_CLARIFYING_QUESTIONS,
        # no matter how many (or how ranked) the model proposed.
        final_questions = tuple(proposed_questions[:MAX_CLARIFYING_QUESTIONS])
        asked_unknowns = {question.targets_unknown for question in final_questions}

        assumptions: list[str] = list(model_assumptions)
        for unknown in request.candidate_unknowns:
            if unknown in asked_unknowns:
                continue
            if any(unknown in assumption for assumption in assumptions):
                continue
            assumptions.append(
                f"No question asked about '{unknown}' — proceeding without it; not among the "
                "top decision-relevant unknowns for this request."
            )

        return ClarificationResult(
            person_id=request.person_id,
            service_category=request.service_category,
            resolved_from_graph=request.known_facts,
            questions=final_questions,
            assumptions=tuple(assumptions),
            urgency=final_urgency,
            urgency_reasoning=urgency_reasoning,
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            clarified_at=datetime.now(UTC),
        )

    def _parse_questions(
        self, parsed: dict[str, object], *, request: ClarificationRequest, raw_text: str
    ) -> tuple[ClarifyingQuestion, ...]:
        raw_questions = require_list(parsed, "questions", agent_id=AGENT_ID)
        questions: list[ClarifyingQuestion] = []
        for raw_question in raw_questions:
            if not isinstance(raw_question, dict):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID, reason="questions entries must be objects", raw_text=raw_text
                )
            targets_unknown = require_str(raw_question, "targets_unknown", agent_id=AGENT_ID)
            if targets_unknown not in request.candidate_unknowns:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=(
                        f"question targets {targets_unknown!r}, which is not a genuine "
                        "candidate_unknown for this request — the graph-first check already "
                        "resolved it, or it was never on the requirement checklist at all"
                    ),
                    raw_text=raw_text,
                )
            text = require_str(raw_question, "text", agent_id=AGENT_ID)
            if not text.strip():
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID, reason="question text must not be blank", raw_text=raw_text
                )
            decision_relevance = require_str(raw_question, "decision_relevance", agent_id=AGENT_ID)
            questions.append(
                ClarifyingQuestion(
                    text=text, targets_unknown=targets_unknown, decision_relevance=decision_relevance
                )
            )
        return tuple(questions)


__all__ = ["AGENT_ID", "MAX_CLARIFYING_QUESTIONS", "RequirementClarifierAgent"]

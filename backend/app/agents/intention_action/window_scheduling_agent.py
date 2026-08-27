"""A25 — Window Scheduling (spec §9.3 Stage 3-4, §15.9, ADR-015).

*Responsibility:* find a real candidate window where the person is
available AND the counterparty is open AND this household's own history
suggests the window will actually result in completion (spec's own
failure mode, §9.5: "use observed completion patterns, not stated
preferences" — never a window chosen on stated availability alone).

*Model tier:* Flash with Pro-tier fallback (spec §15.9 A25) — but only for
the one genuinely unstructured input, `Provider.availability_notes` free
text. The other two signals are deterministic:

- **Person availability** — `app.agents.intention_action.schedule_parsing.
  person_availability_for_window`, ADR-015's real, parseable `SCHEDULE`
  `Constraint.structured` schema. No model call: parsing three known dict
  keys and checking two time ranges for overlap is arithmetic.
- **Historical likelihood** — a real, deterministic read of this person's
  friction-profile evidence (`window_blocker_pattern_support`, the real
  `support_count` of any `window`-type `Pattern` `CHARACTERIZES`-linked to
  them) and their obligation-specific completion evidence (`outcome_count`,
  from `GraphReader.history`), both pre-resolved by the caller. No model
  call — a threshold comparison over real evidence counts, mirroring
  `app.agents.fair_allocator.load_monitor_agent`'s "deterministic verdict,
  Flash/Pro only for narration" precedent, here needing no narration call
  at all since the reasoning is short enough to state directly.

**Counterparty availability** is the one place Flash-with-Pro-fallback
actually applies: `Provider.availability_notes` is real free text ("Mon-Fri
9-6", "by appointment only, call ahead", "10am-1pm, 4pm-8pm except
Wednesdays") that genuinely needs language interpretation against every
real candidate window at once (one call per provider per scheduling
attempt, not one per window — cost discipline). Flash handles the clean,
unambiguous case; escalates to Pro-tier (mirrors `app.agents.intake.
entity_resolution.EntityResolutionAgent`'s exact Flash -> Pro escalation
shape) whenever any window's Flash-tier verdict is `"cannot_determine"` or
the overall confidence does not clear `_COUNTERPARTY_CONFIDENCE_FLOOR`.

*Forbidden behaviour this module never engages in:* it never treats a
person with zero recorded `SCHEDULE` constraints, or a window with no
counterparty at all, as blocking — see `schedule_parsing.
person_availability_for_window`'s own docstring for the documented
open-world default. It never fabricates a "likely" historical verdict
when `outcome_count == 0` and no friction-pattern evidence exists at all
— see `_historical_likelihood` below.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_int, require_list, require_str
from .schedule_parsing import person_availability_for_window
from .types import (
    AvailabilityVerdict,
    CounterpartyAvailabilityResult,
    CounterpartyAvailabilityVerdict,
    CounterpartyWindowVerdict,
    HistoricalLikelihoodResult,
    WindowCandidateEvaluation,
    WindowFindingRequest,
    WindowFindingResult,
)

AGENT_ID = AgentId("A25")

_COUNTERPARTY_CONFIDENCE_FLOOR = 0.7
"""Below this, the Flash-tier counterparty-availability pass is not
trusted on its own — a Pro-tier pass runs before any result is returned
(mirrors `app.agents.intake.entity_resolution._HARD_CONSTRAINT_CONFIDENCE_
FLOOR`'s same escalation role, applied here unconditionally rather than
only under a hard-constraint flag, since every A25 call is scheduling-
relevant enough to warrant it)."""

_WINDOW_BLOCKER_SUPPORT_UNLIKELY_THRESHOLD = 2
"""A `window`-type friction `Pattern` needs at least this much real,
accumulated `support_count` (corrections and/or completions, per ADR-015)
before this module treats it as real evidence a candidate window is
unlikely to result in completion — a single data point is never enough to
call a household pattern "unlikely" (mirrors `Pattern`'s own documented
"never invented from a single data point" discipline)."""

_VALID_COUNTERPARTY_VERDICTS: frozenset[str] = frozenset({"available", "unavailable", "cannot_determine"})

_Window = tuple[datetime, datetime]


def _historical_likelihood(
    *, person_id: NodeId, obligation_id: NodeId, window_blocker_pattern_support: int, outcome_count: int
) -> HistoricalLikelihoodResult:
    """Deterministic — no model call. See module docstring."""
    if window_blocker_pattern_support >= _WINDOW_BLOCKER_SUPPORT_UNLIKELY_THRESHOLD:
        return HistoricalLikelihoodResult(
            person_id=person_id,
            obligation_id=obligation_id,
            likelihood="unlikely",
            reasoning=(
                f"this person's window-blocker friction pattern has {window_blocker_pattern_support} "
                "corroborating instances on file — history suggests scheduling alone has not been "
                "enough to get this kind of task done before"
            ),
            window_blocker_pattern_support=window_blocker_pattern_support,
            outcome_count=outcome_count,
        )
    if outcome_count == 0 and window_blocker_pattern_support == 0:
        return HistoricalLikelihoodResult(
            person_id=person_id,
            obligation_id=obligation_id,
            likelihood="insufficient_data",
            reasoning="no completion history and no window-blocker friction pattern on file for this person",
            window_blocker_pattern_support=window_blocker_pattern_support,
            outcome_count=outcome_count,
        )
    return HistoricalLikelihoodResult(
        person_id=person_id,
        obligation_id=obligation_id,
        likelihood="likely",
        reasoning=(
            f"{outcome_count} real completion outcome(s) on file and no meaningful window-blocker "
            "friction pattern against this person — no evidence scheduling alone will fail here"
        ),
        window_blocker_pattern_support=window_blocker_pattern_support,
        outcome_count=outcome_count,
    )


def _candidate_score(evaluation: WindowCandidateEvaluation) -> tuple[int, int, int]:
    """Deterministic ranking key — higher is better. Excluded candidates
    (hard-blocked person, unavailable counterparty) are filtered out
    before this is ever applied; see `_rank_candidates`."""
    person_score = {
        AvailabilityVerdict.AVAILABLE: 2,
        AvailabilityVerdict.SOFT_AVOID: 1,
        AvailabilityVerdict.CANNOT_DETERMINE: 0,
        AvailabilityVerdict.HARD_BLOCKED: -100,
    }[evaluation.person_availability]
    counterparty_score = {
        "available": 2,
        "cannot_determine": 0,
        None: 1,  # no counterparty at all — neutral, not penalised
        "unavailable": -100,
    }[evaluation.counterparty_availability]
    history_score = {"likely": 1, "insufficient_data": 0, "unlikely": -1}[evaluation.historical_likelihood]
    return (person_score, counterparty_score, history_score)


def _rank_candidates(
    evaluations: tuple[WindowCandidateEvaluation, ...],
) -> tuple[_Window | None, tuple[WindowCandidateEvaluation, ...]]:
    """Deterministic ranking: excludes anything hard-blocked for the
    person or explicitly unavailable for the counterparty, then picks the
    highest-scoring survivor by `_candidate_score`. Returns
    `(best_window, evaluations_with_overall_recommended_set)`.

    `best_window` is `None` only when every candidate was excluded — never
    a fallback guess at an excluded window.
    """
    scored = [(evaluation, _candidate_score(evaluation)) for evaluation in evaluations]
    survivors = [
        (evaluation, score)
        for evaluation, score in scored
        if evaluation.person_availability is not AvailabilityVerdict.HARD_BLOCKED
        and evaluation.counterparty_availability != "unavailable"
    ]
    survivor_windows = {evaluation.window for evaluation, _ in survivors}

    with_recommendation = tuple(
        WindowCandidateEvaluation(
            window=evaluation.window,
            person_availability=evaluation.person_availability,
            counterparty_availability=evaluation.counterparty_availability,
            historical_likelihood=evaluation.historical_likelihood,
            overall_recommended=evaluation.window in survivor_windows,
            reasoning=evaluation.reasoning,
        )
        for evaluation in evaluations
    )

    if not survivors:
        return None, with_recommendation

    best_evaluation, _ = max(survivors, key=lambda pair: pair[1])
    return best_evaluation.window, with_recommendation


def _cast_model_tier(value: Literal["flash", "pro"] | None) -> Literal["deterministic", "flash", "pro"]:
    """Narrows the optional counterparty-check tier to `WindowFindingResult
    .model_tier`'s closed literal — `None` (no counterparty check ran at
    all) becomes `"deterministic"`, mirroring `app.agents.ledger.
    leakage_detection_agent.cast_verdict`'s role."""
    if value is None:
        return "deterministic"
    return value


class WindowSchedulingAgent:
    """A25 Window Scheduling. Dependency-injected on a `GeminiClient`
    only — every graph fact it reasons over (schedule constraints,
    provider availability text, friction-pattern support, outcome counts)
    arrives pre-resolved on `types.WindowFindingRequest`, this codebase's
    established "pre-resolved by the caller" precedent."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def find_window(self, request: WindowFindingRequest) -> WindowFindingResult:
        """Evaluates every candidate window in `request` and picks the
        best real, defensible recommendation.

        Args:
            request: the obligation/person plus every real, pre-resolved
                fact this evaluation needs.

        Returns:
            A `WindowFindingResult` — `best_window` is `None` only when
            no candidate window survived exclusion (never a guessed
            fallback).

        Raises:
            errors.ModelResponseMalformed: the counterparty-availability
                call's response could not be parsed as the expected JSON
                shape.
        """
        historical = _historical_likelihood(
            person_id=request.person_id,
            obligation_id=request.obligation_id,
            window_blocker_pattern_support=request.window_blocker_pattern_support,
            outcome_count=request.outcome_count,
        )

        counterparty_result: CounterpartyAvailabilityResult | None = None
        if request.provider_id is not None and request.provider_availability_notes is not None:
            counterparty_result = self._check_counterparty_availability(
                provider_id=request.provider_id,
                availability_notes=request.provider_availability_notes,
                candidate_windows=request.candidate_windows,
            )
        counterparty_by_window: dict[_Window, CounterpartyAvailabilityVerdict] = (
            {verdict.window: verdict.verdict for verdict in counterparty_result.per_window}
            if counterparty_result is not None
            else {}
        )

        evaluations = []
        for window in request.candidate_windows:
            person_verdict = person_availability_for_window(request.person_schedule_constraints, window)
            counterparty_verdict = (
                counterparty_by_window.get(window) if counterparty_result is not None else None
            )
            reasoning = (
                f"person: {person_verdict.value}; "
                f"counterparty: {counterparty_verdict or 'n/a'}; "
                f"history: {historical.likelihood}"
            )
            evaluations.append(
                WindowCandidateEvaluation(
                    window=window,
                    person_availability=person_verdict,
                    counterparty_availability=counterparty_verdict,
                    historical_likelihood=historical.likelihood,
                    overall_recommended=False,  # set for real by _rank_candidates below
                    reasoning=reasoning,
                )
            )

        best_window, ranked_evaluations = _rank_candidates(tuple(evaluations))
        counterparty_tier = counterparty_result.model_tier if counterparty_result is not None else None

        return WindowFindingResult(
            obligation_id=request.obligation_id,
            person_id=request.person_id,
            evaluations=ranked_evaluations,
            best_window=best_window,
            confidence=counterparty_result.confidence if counterparty_result is not None else 1.0,
            model_tier=_cast_model_tier(counterparty_tier),
        )

    def _check_counterparty_availability(
        self, *, provider_id: NodeId, availability_notes: str, candidate_windows: tuple[_Window, ...]
    ) -> CounterpartyAvailabilityResult:
        result = self._call_counterparty(
            provider_id=provider_id,
            availability_notes=availability_notes,
            candidate_windows=candidate_windows,
            tier=ModelTier.FLASH,
        )
        escalated = False
        needs_escalation = result.confidence < _COUNTERPARTY_CONFIDENCE_FLOOR or any(
            verdict.verdict == "cannot_determine" for verdict in result.per_window
        )
        if needs_escalation:
            result = self._call_counterparty(
                provider_id=provider_id,
                availability_notes=availability_notes,
                candidate_windows=candidate_windows,
                tier=ModelTier.PRO,
            )
            escalated = True

        return CounterpartyAvailabilityResult(
            provider_id=provider_id,
            per_window=result.per_window,
            confidence=result.confidence,
            model_tier=result.model_tier,
            escalated_to_pro=escalated,
            prompt_version=result.prompt_version,
            invocation_id=result.invocation_id,
        )

    def _call_counterparty(
        self,
        *,
        provider_id: NodeId,
        availability_notes: str,
        candidate_windows: tuple[_Window, ...],
        tier: ModelTier,
    ) -> CounterpartyAvailabilityResult:
        prompt = load_prompt("A25_COUNTERPARTY")
        windows_block = "\n".join(
            f"- index={i}: {start.isoformat()} to {end.isoformat()}"
            for i, (start, end) in enumerate(candidate_windows)
        )
        rendered = prompt.text.format(availability_notes=availability_notes, windows_block=windows_block)
        call_result = self._gemini_client.generate_structured(agent_id=AGENT_ID, tier=tier, prompt=rendered)
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_items = require_list(parsed, "per_window", agent_id=AGENT_ID)

        per_window: list[CounterpartyWindowVerdict] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID, reason="per_window entries must be objects", raw_text=call_result.text
                )
            index = require_int(raw_item, "index", agent_id=AGENT_ID)
            if not (0 <= index < len(candidate_windows)):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"window index {index!r} out of range",
                    raw_text=call_result.text,
                )
            verdict_raw = require_str(raw_item, "verdict", agent_id=AGENT_ID)
            if verdict_raw not in _VALID_COUNTERPARTY_VERDICTS:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"unrecognised verdict {verdict_raw!r}",
                    raw_text=call_result.text,
                )
            per_window.append(
                CounterpartyWindowVerdict(
                    window=candidate_windows[index],
                    verdict=_cast_counterparty_verdict(verdict_raw),
                    reasoning=require_str(raw_item, "reasoning", agent_id=AGENT_ID),
                )
            )

        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        return CounterpartyAvailabilityResult(
            provider_id=provider_id,
            per_window=tuple(per_window),
            confidence=confidence,
            model_tier="pro" if tier is ModelTier.PRO else "flash",
            escalated_to_pro=False,
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )


def _cast_counterparty_verdict(value: str) -> CounterpartyAvailabilityVerdict:
    """Narrows a validated string to the closed verdict literal — mirrors
    `app.agents.ledger.leakage_detection_agent.cast_verdict`'s role."""
    if value == "available":
        return "available"
    if value == "unavailable":
        return "unavailable"
    return "cannot_determine"


__all__ = ["AGENT_ID", "WindowSchedulingAgent"]

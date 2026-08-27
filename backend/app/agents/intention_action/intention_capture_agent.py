"""A22 — Intention Capture (spec §9.3 Stage 1, §15.9).

*Responsibility:* two distinct real detections, spec's own Stage 1 split:

1. **Passive intention capture** — a household intention expressed in
   passing, in a note or message, never yet written as an `Obligation`
   (spec's own example: "we should really get the AC serviced"). Real
   Flash-tier language work — recognising an intention buried in ordinary
   conversation is genuine (if cheap) reasoning, not a template match.
2. **Stale-obligation detection** — an already-written `Obligation` gone
   stale. Purely deterministic (see `_is_stale`'s docstring for the real,
   documented threshold) — no Gemini call backs this at all, mirroring
   `app.agents.fair_allocator.load_monitor_agent`'s "the verdict itself is
   a deterministic threshold comparison" precedent exactly.

*Model tier:* Flash for passive capture; no model call for staleness
detection (see above).

*Forbidden:* **acting directly.** This module holds no `ToolRegistry`, no
`GraphWriter` import, no import of anything under `app.tools` or
`app.arbitration` at all — both detection methods return a real, typed
detection record and nothing else. Writing the resulting `Obligation` (for
a captured intention) or re-routing a stale one is a downstream caller's
job (A15 Obligation Writer, or a human), never this agent's.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId, Obligation, ObligationStatus

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_str
from .types import PassiveIntentionDetection, StaleObligationDetection

AGENT_ID = AgentId("A22")

_STALE_AFTER_DEADLINE_DAYS = 3
"""An `Obligation` with a real `due_at` or `must_start_by` that has passed
by at least this many days, with no status progression since (see
`_is_stale`'s use of `provenance.created_at` as the last-touched signal),
is stale — a short, deliberate grace period (not zero) so a routine
same-week catch-up does not immediately count as "stale," while still
catching the pattern spec §9.1's diary-study finding names: the intention
was remembered and still didn't happen at the moment of action."""

_STALE_NO_DEADLINE_DAYS = 21
"""An `Obligation` with no `due_at` and no `must_start_by` at all (an
open-ended intention, spec's own "call the dentist" worked example) is
stale once its current version has sat untouched for this many days.
Three weeks is a deliberately conservative floor — long enough that a
task genuinely still "on the list, just not urgent yet" is not
prematurely flagged, short enough to catch real languishing well before
spec's own extreme "untouched for four months" demo case. A documented,
revisitable product constant, not a guess (mirrors `app.agents.
fair_allocator.load_monitor_agent._IMBALANCE_DRIFT_THRESHOLD`'s same
role)."""

_TERMINAL_STATUSES = frozenset(
    {ObligationStatus.COMPLETED, ObligationStatus.DROPPED, ObligationStatus.SUPERSEDED}
)


def _is_stale(obligation: Obligation, *, now: datetime) -> tuple[bool, str, int, int]:
    """The real, deterministic staleness rule.

    "Last touched" is `obligation.provenance.created_at` — a graph write
    creates a new version on any real update (PHASES.md §2.2: writes
    create versions, never mutate in place), so the *current* version's
    `created_at` is a real, non-fabricated signal of when this obligation
    was last genuinely acted on, without inventing a new field.

    Returns:
        `(is_stale, reason, days_stale, threshold_days)`.
    """
    if obligation.status in _TERMINAL_STATUSES:
        return False, "", 0, 0

    deadline = obligation.due_at or obligation.must_start_by
    if deadline is not None:
        overdue_days = (now - deadline).days
        if overdue_days >= _STALE_AFTER_DEADLINE_DAYS:
            deadline_kind = "due" if obligation.due_at is not None else "must start by"
            return (
                True,
                f"{deadline_kind} {overdue_days} day(s) ago, with no status change since",
                overdue_days,
                _STALE_AFTER_DEADLINE_DAYS,
            )
        return False, "", 0, 0

    untouched_days = (now - obligation.provenance.created_at).days
    if untouched_days >= _STALE_NO_DEADLINE_DAYS:
        return (
            True,
            f"no deadline set, and untouched for {untouched_days} day(s)",
            untouched_days,
            _STALE_NO_DEADLINE_DAYS,
        )
    return False, "", 0, 0


class IntentionCaptureAgent:
    """A22 Intention Capture. Dependency-injected on a `GeminiClient`
    only — no tool of any kind (see module docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def detect_passive_intention(
        self, *, source_text: str, speaker_person_id: NodeId | None
    ) -> PassiveIntentionDetection | None:
        """Flash: looks for a real household intention expressed in
        passing within `source_text`.

        Args:
            source_text: the real, unmodified message/note text.
            speaker_person_id: the speaker, if already known from
                channel/context — never guessed by this method itself.

        Returns:
            A `PassiveIntentionDetection`, or `None` when the model finds
            no real intention expressed in the text.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape.
        """
        prompt = load_prompt("A22")
        rendered = prompt.text.format(source_text=source_text)
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        found = parsed.get("intention_found")
        if found is not True:
            return None

        return PassiveIntentionDetection(
            source_text=source_text,
            person_id=speaker_person_id,
            intention_summary=require_str(parsed, "intention_summary", agent_id=AGENT_ID),
            suggested_title=require_str(parsed, "suggested_title", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            reasoning=require_str(parsed, "reasoning", agent_id=AGENT_ID),
            model_tier="flash",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def detect_stale_obligation(
        self, obligation: Obligation, *, now: datetime
    ) -> StaleObligationDetection | None:
        """Deterministic: checks one real `Obligation` against the
        documented staleness thresholds (`_STALE_AFTER_DEADLINE_DAYS` /
        `_STALE_NO_DEADLINE_DAYS`). No Gemini call.

        Args:
            obligation: the real `Obligation` to check.
            now: the reference time (injected, never `datetime.now()`
                directly, so this stays testable and reproducible).

        Returns:
            A `StaleObligationDetection`, or `None` when `obligation` is
            not stale (including every terminal-status obligation, which
            is never stale by definition).
        """
        is_stale, reason, days_stale, threshold_days = _is_stale(obligation, now=now)
        if not is_stale:
            return None
        return StaleObligationDetection(
            obligation_id=obligation.id,
            title=obligation.title,
            reason=reason,
            days_stale=days_stale,
            threshold_days=threshold_days,
            detected_at=now,
        )


__all__ = ["AGENT_ID", "IntentionCaptureAgent"]

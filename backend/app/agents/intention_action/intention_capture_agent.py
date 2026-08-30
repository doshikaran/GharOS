"""A22 — Intention Capture (spec §9.3 Stage 1, §15.9).

*Responsibility:* two distinct real detections, spec's own Stage 1 split:

1. **Passive intention capture** — a household intention expressed in
   passing, in a note or message, never yet written as an `Obligation`
   (spec's own example: "we should really get the AC serviced"). Real
   Flash-tier language work — recognising an intention buried in ordinary
   conversation is genuine (if cheap) reasoning, not a template match.
2. **Stale-obligation detection** — an already-written `Obligation` gone
   stale. Purely deterministic — no Gemini call backs this at all,
   mirroring `app.agents.fair_allocator.load_monitor_agent`'s "the verdict
   itself is a deterministic threshold comparison" precedent exactly. The
   rule itself lives in `app.solvers.staleness` (`is_stale` /
   `StalenessCheck`), the shared, canonical home A11 Graph Maintainer also
   reuses graph-wide (ADR-021); this agent imports it rather than carrying
   its own copy. Repaying DEBT-013 (the byte-for-byte duplication that
   existed while E1 could not edit this E2-owned file) — Phase 15.

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
from contracts.graph_types import AgentId, NodeId, Obligation

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.staleness import is_stale
from .json_utils import parse_json_response, require_float, require_str
from .types import PassiveIntentionDetection, StaleObligationDetection

AGENT_ID = AgentId("A22")


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
        """Deterministic: checks one real `Obligation` against the shared,
        canonical staleness rule in `app.solvers.staleness.is_stale`. No
        Gemini call.

        Args:
            obligation: the real `Obligation` to check.
            now: the reference time (injected, never `datetime.now()`
                directly, so this stays testable and reproducible).

        Returns:
            A `StaleObligationDetection`, or `None` when `obligation` is
            not stale (including every terminal-status obligation, which
            is never stale by definition).
        """
        check = is_stale(obligation, now=now)
        if not check.is_stale:
            return None
        return StaleObligationDetection(
            obligation_id=obligation.id,
            title=obligation.title,
            reason=check.reason,
            days_stale=check.days_stale,
            threshold_days=check.threshold_days,
            detected_at=now,
        )


__all__ = ["AGENT_ID", "IntentionCaptureAgent"]

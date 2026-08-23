"""A4 — Message Normalization Agent (spec §15.2).

*Responsibility:* WhatsApp exports/screenshots, UPI SMS, app
notifications -> normalized events. Multi-language and code-mixed
tolerant.
*Model tier:* Flash only.
*Forbidden:* action, implication — this agent never decides an obligation
follows from a message (that is A12's job, Phase 4) and never sends or
writes anything.
*Failure discipline (not in spec's one-line Forbidden list, but explicit
in this phase's brief):* never "cleans up" code-mixed text into fluent
monolingual text — `NormalizedEvent.original_text` is always the model's
verbatim echo of the source, never a translation or a tidied paraphrase.
This module does not translate, re-script, or otherwise transform the
text content itself; it only classifies and attributes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from contracts.agents import AgentOutput, ModelTier
from contracts.graph_types import AgentId, Derivation

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import optional_str, parse_json_response, require_float, require_list, require_str

AGENT_ID = AgentId("A4")


class MessageEventType(StrEnum):
    COMMITMENT = "commitment"
    COMPLAINT = "complaint"
    LEAVE_NOTIFICATION = "leave_notification"
    INTENTION = "intention"
    INFORMATIONAL = "informational"


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """One classified message. `original_text` is always verbatim — see
    module docstring."""

    speaker: str | None
    original_text: str
    event_type: MessageEventType
    language_note: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MessageNormalizationResult:
    agent_output: AgentOutput
    events: tuple[NormalizedEvent, ...]


class MessageNormalizationAgent:
    """A4 Message Normalization Agent. Dependency-injected on a
    `GeminiClient`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def normalize(self, *, transcript: str) -> MessageNormalizationResult:
        """Splits `transcript` into normalized, classified events.

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape.
        """
        prompt = load_prompt("A4")
        rendered = prompt.text.format(transcript_body=transcript)

        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        events: list[NormalizedEvent] = []
        for raw_event in require_list(parsed, "events", agent_id=AGENT_ID):
            if not isinstance(raw_event, dict):
                continue
            events.append(
                NormalizedEvent(
                    speaker=optional_str(raw_event, "speaker"),
                    original_text=require_str(raw_event, "original_text", agent_id=AGENT_ID),
                    event_type=MessageEventType(require_str(raw_event, "event_type", agent_id=AGENT_ID)),
                    language_note=require_str(raw_event, "language_note", agent_id=AGENT_ID),
                    confidence=require_float(raw_event, "confidence", agent_id=AGENT_ID, default=0.5),
                )
            )

        overall_confidence = sum(event.confidence for event in events) / len(events) if events else 0.0
        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=ModelTier.FLASH,
            prompt_version=prompt.version,
            confidence=overall_confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return MessageNormalizationResult(agent_output=agent_output, events=tuple(events))


__all__ = [
    "AGENT_ID",
    "MessageEventType",
    "MessageNormalizationAgent",
    "MessageNormalizationResult",
    "NormalizedEvent",
]

"""A66 — Speaker Identification Agent (spec §14.4, §15.11, PHASES.md
Phase 13, ADR-020) — E3's `backend/app/voice/`.

*Responsibility:* given a household's enrolled reference voice clips and
the current turn's real audio, determine which household member (if any)
is speaking — a real, live multimodal comparison call per enrolled
speaker, never a hardcoded or fabricated match.

**Real comparison, not a heuristic.** For each `types.EnrolledSpeaker`
candidate, this module sends BOTH audio clips (the enrolled reference and
the current turn) in a single multimodal Gemini call, asking directly
"are these the same speaker, and how confident are you?" — the model's
own real judgment, never string/embedding-distance code this project does
not have the infrastructure for. `matched_against_person_ids` on the
result always lists every candidate actually compared, whether or not a
match was found — proof that "no comparisons attempted" and "no enrolled
speaker matched" are never conflated.

**"No enrolled match clearing the confidence floor -> unknown speaker"**
(spec §15.11 A66's own failure mode) is structural: `identify` returns
`person_id=None` whenever no candidate's reported `same_speaker=True`
confidence clears `_SPEAKER_MATCH_CONFIDENCE_FLOOR` — including, honestly,
the case of zero enrolled candidates at all (a fresh household with
nobody enrolled yet). The caller (`session_manager.py`) is responsible
for spec's own consequence of this: an unidentified speaker is restricted
to R0/R1 actions only — never an R2/R3 approval.

*Model tier:* Flash (ADR-020 Decision 4: "A62/A63/A64/A66 stay
Flash-tier").

*Forbidden:* fabricating a match; treating "no enrolled speakers" as a
reason to skip real comparisons some other way (there is nothing to
compare, so nothing is compared — that IS the real behaviour, not a
shortcut). Holds no tool, no import of `app.arbitration` — see
`backend/tests/test_voice_infra_arbitration_boundary.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from app.agents.voice.json_utils import parse_json_response, require_bool, require_float
from app.reasoning.gemini_client import GeminiClient, MediaPart

from .types import EnrolledSpeaker, SpeakerIdentificationResult

AGENT_ID = AgentId("A66")

_SPEAKER_MATCH_CONFIDENCE_FLOOR = 0.65
"""Below this, a candidate's reported `same_speaker=True` confidence is
not trusted as a real match — the speaker is treated as unidentified
rather than assigning them to the best-scoring-but-still-weak candidate."""

_PROMPT = """You are the speaker identification stage of a household operating system.

You are given two short audio clips:
- CLIP A: a previously enrolled reference recording of a named household member.
- CLIP B: the current turn's audio, whose speaker is unknown.

Determine whether the speaker in CLIP B is the SAME PERSON as the speaker in CLIP A. Base your judgment \
only on voice characteristics (pitch, timbre, cadence, accent) — never on what is said.

Respond with a single JSON object and nothing else:
{"same_speaker": true or false, "confidence": 0.0, "reasoning": "one short sentence"}
"""


@dataclass(frozen=True, slots=True)
class _Comparison:
    person_id: NodeId
    display_name: str
    same_speaker: bool
    confidence: float


class SpeakerIdentificationAgent:
    """A66 Speaker Identification Agent. Dependency-injected on a
    `GeminiClient` only — no `GraphReader`, no tool of any kind (the
    caller resolves `Person.voiceprint_ref` -> reference bytes itself, per
    `types.EnrolledSpeaker`'s own docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def identify(
        self,
        *,
        turn_audio: bytes,
        turn_mime_type: str,
        enrolled_speakers: tuple[EnrolledSpeaker, ...],
    ) -> SpeakerIdentificationResult:
        """Identifies the real speaker of `turn_audio` among
        `enrolled_speakers`.

        Args:
            turn_audio: the current turn's real audio bytes.
            turn_mime_type: `turn_audio`'s real MIME type.
            enrolled_speakers: every household member with a stored
                reference clip — resolved by the caller from `Person.
                voiceprint_ref` via `RawPayloadStore`. May be empty (a
                household with nobody enrolled yet) — this is a normal,
                real input, never a caller error.

        Returns:
            A `SpeakerIdentificationResult`. `person_id` is `None` when no
            candidate's `same_speaker=True` confidence clears
            `_SPEAKER_MATCH_CONFIDENCE_FLOOR` (including the
            zero-candidates case).

        Raises:
            app.agents.voice.errors.ModelResponseMalformed: a comparison
                response could not be parsed as the expected JSON shape.
        """
        comparisons = [
            self._compare(turn_audio=turn_audio, turn_mime_type=turn_mime_type, candidate=candidate)
            for candidate in enrolled_speakers
        ]

        matches = [
            c for c in comparisons if c.same_speaker and c.confidence >= _SPEAKER_MATCH_CONFIDENCE_FLOOR
        ]
        now = datetime.now(UTC)
        matched_against = tuple(candidate.person_id for candidate in enrolled_speakers)

        if not matches:
            best_confidence = max((c.confidence for c in comparisons), default=0.0)
            return SpeakerIdentificationResult(
                person_id=None,
                display_name=None,
                confidence=best_confidence,
                matched_against_person_ids=matched_against,
                invocation_id=uuid.uuid4().hex,
                identified_at=now,
            )

        best = max(matches, key=lambda c: c.confidence)
        return SpeakerIdentificationResult(
            person_id=best.person_id,
            display_name=best.display_name,
            confidence=best.confidence,
            matched_against_person_ids=matched_against,
            invocation_id=uuid.uuid4().hex,
            identified_at=now,
        )

    def _compare(self, *, turn_audio: bytes, turn_mime_type: str, candidate: EnrolledSpeaker) -> _Comparison:
        call_result = self._gemini_client.generate_multimodal(
            agent_id=AGENT_ID,
            tier=ModelTier.FLASH,
            prompt=_PROMPT,
            media=(
                MediaPart(data=candidate.reference_audio, mime_type=candidate.reference_mime_type),
                MediaPart(data=turn_audio, mime_type=turn_mime_type),
            ),
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        same_speaker = require_bool(parsed, "same_speaker", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID)
        return _Comparison(
            person_id=candidate.person_id,
            display_name=candidate.display_name,
            same_speaker=same_speaker,
            confidence=confidence,
        )


__all__ = ["AGENT_ID", "SpeakerIdentificationAgent"]

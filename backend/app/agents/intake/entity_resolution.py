"""A5 — Entity Resolution Agent (spec §15.2, §21.1).

*Responsibility:* map mentions to graph `Person` nodes across scripts and
aliases — spec's own worked example: "आरव", "Aarav", "Arav" resolve to one
PERSON.
*Model tier:* Flash by default; escalates to Pro-tier (allowlisted,
`model_router.PRO_TIER_ALLOWLIST`) whenever the Flash pass reports
`"ambiguous"`, or whenever `hard_constraint_context` is set and Flash's
own confidence does not clear `_HARD_CONSTRAINT_CONFIDENCE_FLOOR` — spec
§21.1: "cross-script entity resolution... Flash, Pro-tier on ambiguity."
*Forbidden:* creating entities above a confidence threshold without
confirmation — this agent never writes a `Person` node itself (it has no
`GraphWriter`); its `"new_person"` verdict is advisory only, always
requiring a downstream confirmation step this phase does not build.
*Failure:* **never guess on hard-constraint-bearing entities.** If
`hard_constraint_context` is `True` and the mention is still ambiguous
after the Pro-tier escalation pass, `resolve` raises
`contracts.errors.AmbiguousEntity` rather than returning any single
candidate — structurally impossible for a caller to accidentally treat a
picked-at-random candidate as the resolution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from contracts.agents import AgentOutput, ModelTier
from contracts.errors import AmbiguousEntity
from contracts.graph_types import AgentId, Derivation, NodeId, Person

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiCallResult, GeminiClient
from .json_utils import optional_str, parse_json_response, require_float, require_list, require_str

AGENT_ID = AgentId("A5")

_HARD_CONSTRAINT_CONFIDENCE_FLOOR = 0.85
"""Below this, a hard-constraint-bearing mention's Flash-tier resolution
is not trusted on its own — a Pro-tier pass runs before any result is
returned, even if Flash's own verdict was `"matched_existing"`."""


class ResolutionVerdict(StrEnum):
    MATCHED_EXISTING = "matched_existing"
    NEW_PERSON = "new_person"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class _RawResolution:
    """Internal: one Gemini call's parsed verdict, before the
    escalation/never-guess policy in `resolve` decides whether to trust
    it or make a second call."""

    call_result: GeminiCallResult
    verdict: ResolutionVerdict
    confidence: float
    parsed: dict[str, object]


@dataclass(frozen=True, slots=True)
class EntityResolutionResult:
    agent_output: AgentOutput
    resolution: ResolutionVerdict
    matched_person_id: NodeId | None
    candidate_person_ids: tuple[NodeId, ...]
    reasoning: str
    confidence: float
    escalated_to_pro: bool


def _known_people_block(known_people: tuple[Person, ...]) -> str:
    lines = []
    for person in known_people:
        aliases = ", ".join(person.aliases) if person.aliases else "(none recorded)"
        lines.append(f'- id="{person.id}" display_name="{person.display_name}" aliases=[{aliases}]')
    return "\n".join(lines) if lines else "(no known people recorded yet)"


class EntityResolutionAgent:
    """A5 Entity Resolution Agent. Dependency-injected on a
    `GeminiClient`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def resolve(
        self,
        *,
        mention_text: str,
        mention_context: str,
        known_people: tuple[Person, ...],
        hard_constraint_context: bool = False,
    ) -> EntityResolutionResult:
        """Resolves one person mention against `known_people`.

        Args:
            mention_text: the raw mention as it appears in the source
                (any script/transliteration).
            mention_context: a short surrounding-text excerpt, helps
                disambiguate ("Aarav's teacher says..." vs a bare name).
            known_people: the household's current `Person` nodes.
            hard_constraint_context: `True` when this resolution decides
                which person a hard constraint (e.g. an allergy) applies
                to — tightens the escalation and never-guess policy (see
                module docstring).

        Raises:
            ModelResponseMalformed: a model response could not be parsed.
            AmbiguousEntity: `hard_constraint_context` is `True` and the
                mention is still ambiguous after Pro-tier escalation.
        """
        prompt = load_prompt("A5")
        rendered = prompt.text.format(
            mention_text=mention_text,
            mention_context=mention_context,
            hard_constraint_context=str(hard_constraint_context),
            known_people_block=_known_people_block(known_people),
        )

        flash = self._call(rendered, tier=ModelTier.FLASH)

        used_tier = ModelTier.FLASH
        resolution = flash
        escalated = False
        needs_escalation = flash.verdict is ResolutionVerdict.AMBIGUOUS or (
            hard_constraint_context and flash.confidence < _HARD_CONSTRAINT_CONFIDENCE_FLOOR
        )
        if needs_escalation:
            resolution = self._call(rendered, tier=ModelTier.PRO)
            used_tier = ModelTier.PRO
            escalated = True

        matched_person_id_raw = optional_str(resolution.parsed, "matched_person_id")
        matched_person_id = NodeId(matched_person_id_raw) if matched_person_id_raw else None
        candidate_ids = tuple(
            NodeId(str(candidate))
            for candidate in require_list(resolution.parsed, "candidate_person_ids", agent_id=AGENT_ID)
        )
        reasoning = require_str(resolution.parsed, "reasoning", agent_id=AGENT_ID)

        if hard_constraint_context and resolution.verdict is ResolutionVerdict.AMBIGUOUS:
            raise AmbiguousEntity(
                mention=mention_text,
                candidates=tuple(str(cid) for cid in candidate_ids),
                hard_constraint_bearing=True,
            )

        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=used_tier,
            prompt_version=prompt.version,
            confidence=resolution.confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return EntityResolutionResult(
            agent_output=agent_output,
            resolution=resolution.verdict,
            matched_person_id=matched_person_id,
            candidate_person_ids=candidate_ids,
            reasoning=reasoning,
            confidence=resolution.confidence,
            escalated_to_pro=escalated,
        )

    def _call(self, rendered_prompt: str, *, tier: ModelTier) -> _RawResolution:
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=tier, prompt=rendered_prompt
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        verdict = ResolutionVerdict(require_str(parsed, "resolution", agent_id=AGENT_ID))
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        return _RawResolution(call_result=call_result, verdict=verdict, confidence=confidence, parsed=parsed)


__all__ = ["AGENT_ID", "EntityResolutionAgent", "EntityResolutionResult", "ResolutionVerdict"]

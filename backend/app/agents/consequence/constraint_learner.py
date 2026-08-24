"""A16 — Constraint Learner (spec §7.4, §15.4).

*Responsibility:* detect repeated signals across multiple SOURCE_DOCUMENTs
that suggest a new, never-explicitly-recorded household constraint.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — judging
whether a repeated textual pattern across several documents is genuinely
a consistent household rule (versus topically-similar coincidence) is
interpretation, not lookup.

*Forbidden:* **writing a hard constraint without human confirmation** —
enforced two ways, structurally, not just by convention:

1. This module has **no `GraphWriter` import anywhere** — it is
   physically incapable of writing any node, hard or soft, to the graph.
2. Its entire output type, `types.CandidateConstraint`, has a `status`
   field whose only value is the `Literal["pending_confirmation"]` —
   there is no code path, in this class or that dataclass, that can
   produce a "confirmed" candidate. A real `contracts.graph_types.
   Constraint` node only ever gets written once a separate,
   human-confirmation-gated step (outside this phase's scope — Phase 5+)
   consumes a `CandidateConstraint` and a person's explicit yes.

A minimum-support gate (`_MIN_SUPPORT_COUNT`) skips groups with too few
distinct source documents *before* spending a Pro-tier call at all — cost
discipline, and it also means "repeated" is a real, checked precondition
rather than a single excerpt masquerading as a pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId, ConstraintKind, ConstraintSeverity, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_bool, require_dict, require_float, require_str
from .types import CandidateConstraint

AGENT_ID = AgentId("A16")

logger = structlog.get_logger(__name__)

_MIN_SUPPORT_COUNT = 2
"""Minimum number of *distinct* SOURCE_DOCUMENTs a signal must appear in
before A16 even considers it — a single occurrence is not "repeated," and
running a Pro-tier call over it would be pure cost with no chance of a
genuine finding (a group below this is skipped without any Gemini call)."""


@dataclass(frozen=True, slots=True)
class SignalOccurrence:
    """One textual excerpt possibly describing a recurring rule,
    attributed to the SOURCE_DOCUMENT it came from."""

    source_document_id: NodeId
    excerpt: str


@dataclass(frozen=True, slots=True)
class RepeatedSignalGroup:
    """A caller-assembled group of `SignalOccurrence`s the caller already
    judges as plausibly describing the same underlying pattern (e.g. via
    keyword/topic clustering upstream) — A16's own job starts from here:
    deciding whether the group genuinely IS one consistent rule, not
    clustering documents in the first place."""

    topic_hint: str
    occurrences: tuple[SignalOccurrence, ...]

    def distinct_source_document_count(self) -> int:
        return len({occurrence.source_document_id for occurrence in self.occurrences})


def _occurrences_block(occurrences: tuple[SignalOccurrence, ...]) -> str:
    return "\n".join(
        f'- (from document {occurrence.source_document_id}): "{occurrence.excerpt}"'
        for occurrence in occurrences
    )


class ConstraintLearnerAgent:
    """A16 Constraint Learner. Dependency-injected on a `GeminiClient`
    only — deliberately no `GraphReader`/`GraphWriter` of any kind (see
    module docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def learn(self, group: RepeatedSignalGroup) -> CandidateConstraint | None:
        """Judges whether `group` describes a genuine repeated household
        constraint.

        Args:
            group: a caller-assembled group of same-topic excerpts from
                distinct documents.

        Returns:
            A `CandidateConstraint` (always `status="pending_confirmation"`)
            if the model judges this a genuine repeated constraint,
            otherwise `None` — either because support is too thin to even
            evaluate, or because the model judged it not a real pattern.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape.
        """
        support_count = group.distinct_source_document_count()
        if support_count < _MIN_SUPPORT_COUNT:
            logger.info(
                "agents.consequence.a16.skipped_insufficient_support",
                topic_hint=group.topic_hint,
                support_count=support_count,
                floor=_MIN_SUPPORT_COUNT,
            )
            return None

        prompt = load_prompt("A16")
        rendered = prompt.text.format(occurrences_block=_occurrences_block(group.occurrences))
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        is_constraint = require_bool(parsed, "is_constraint", agent_id=AGENT_ID, default=False)
        if not is_constraint:
            logger.info(
                "agents.consequence.a16.judged_not_a_constraint",
                topic_hint=group.topic_hint,
                support_count=support_count,
            )
            return None

        kind = ConstraintKind(require_str(parsed, "kind", agent_id=AGENT_ID))
        severity = ConstraintSeverity(require_str(parsed, "severity_if_confirmed", agent_id=AGENT_ID))
        structured_raw = require_dict(parsed, "structured", agent_id=AGENT_ID)
        structured = {str(key): str(value) for key, value in structured_raw.items()}
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        candidate = CandidateConstraint(
            pending_id=f"pending-constraint:{uuid.uuid4().hex}",
            kind=kind,
            severity_if_confirmed=severity,
            structured=structured,
            original_text_examples=tuple(occurrence.excerpt for occurrence in group.occurrences),
            supporting_source_document_ids=tuple(
                sorted({occurrence.source_document_id for occurrence in group.occurrences})
            ),
            support_count=support_count,
            confidence=confidence,
        )
        logger.info(
            "agents.consequence.a16.candidate_constraint_produced",
            topic_hint=group.topic_hint,
            kind=kind.value,
            severity=severity.value,
            support_count=support_count,
        )
        return candidate


__all__ = ["AGENT_ID", "ConstraintLearnerAgent", "RepeatedSignalGroup", "SignalOccurrence"]

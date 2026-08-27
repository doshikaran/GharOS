"""A23 — Blocker Diagnosis Agent, core (spec §9.3 Stage 2, §15.9).

*Responsibility:* determine the specific obstacle per the six-type
taxonomy (`types.BlockerType`) — information / decision / window /
first-step-ambiguity / dependency / aversion. The genuine judgment step of
the whole subsystem: spec's own worked example (the "call the dentist"
task, untouched for months) shows why this is hard — forgetting explains
only ~10-14% of unfulfilled intentions (spec §9.1), so *which* of the
other six real obstacles is actually operating needs real reasoning over
the specific household's specific situation, not a rule-based guess.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — spec §21.1
names "blocker diagnosis" explicitly as one of the named hard reasoning
steps.

*Output discipline — spec's own "states its diagnosis so it can be
corrected":* `types.BlockerDiagnosis.diagnosis_text` is a first-class,
complete, human-readable field, never something a caller has to infer
from `blocker_type` plus a confidence score alone. A human reading only
`diagnosis_text` must be able to agree or issue a real correction (see
`friction_profile.apply_diagnosis_correction`).

*Forbidden:* **unblocking.** This module holds no `ToolRegistry` at all —
no read, no search, no draft, no write import of any kind. Every fact it
reasons over arrives pre-resolved on `types.BlockerDiagnosisRequest`
(this codebase's established "pre-resolved by the caller" precedent,
e.g. `app.agents.fair_allocator.valuation_extraction_agent`'s
`ValuationExtractionRequest`) — diagnosis only, structurally incapable of
also acting on what it diagnoses.
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
from .types import BlockerDiagnosis, BlockerDiagnosisRequest, BlockerType

AGENT_ID = AgentId("A23")

_VALID_BLOCKER_TYPES: frozenset[str] = frozenset(member.value for member in BlockerType)


def _known_facts_block(request: BlockerDiagnosisRequest) -> str:
    if not request.known_facts:
        return "(no additional known facts)"
    return "\n".join(f"- {fact}" for fact in request.known_facts)


def _friction_profile_block(request: BlockerDiagnosisRequest) -> str:
    return request.friction_profile_summary or "(no prior friction profile on file for this person)"


def _prior_diagnosis_block(request: BlockerDiagnosisRequest) -> str:
    prior = request.prior_diagnosis
    if prior is None:
        return "(this is a first diagnosis, not a re-diagnosis)"
    return (
        f'Prior diagnosis: "{prior.diagnosis_text}" (type={prior.blocker_type.value}, '
        f"confidence={prior.confidence:.2f}). This attempt to unblock using that diagnosis "
        "failed — the first diagnosis may have been wrong. Reconsider from the evidence, "
        "do not simply repeat the prior conclusion."
    )


class BlockerDiagnosisAgent:
    """A23 Blocker Diagnosis. Dependency-injected on a `GeminiClient`
    only — no tool of any kind (see module docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def diagnose(self, request: BlockerDiagnosisRequest) -> BlockerDiagnosis:
        """Diagnoses one obligation's blocker.

        Args:
            request: every real, caller-resolved fact this diagnosis
                should consider, plus (on a re-diagnosis) the prior
                diagnosis that failed to unblock the task.

        Returns:
            A `BlockerDiagnosis` — `diagnosis_text` always a complete,
            standalone, human-readable statement.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, named a blocker
                type outside the six-type taxonomy, or named an
                alternative-considered type identical to its own chosen
                `blocker_type`.
        """
        prompt = load_prompt("A23")
        rendered = prompt.text.format(
            obligation_title=request.obligation_title,
            obligation_type=request.obligation_type,
            status=request.status,
            effort_estimate_minutes=request.effort_estimate_minutes,
            due_at=request.due_at.isoformat() if request.due_at else "(none set)",
            must_start_by=request.must_start_by.isoformat() if request.must_start_by else "(none set)",
            known_facts_block=_known_facts_block(request),
            friction_profile_block=_friction_profile_block(request),
            prior_diagnosis_block=_prior_diagnosis_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        blocker_type_raw = require_str(parsed, "blocker_type", agent_id=AGENT_ID)
        if blocker_type_raw not in _VALID_BLOCKER_TYPES:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=(
                    f"unrecognised blocker_type {blocker_type_raw!r}; "
                    f"expected one of {sorted(_VALID_BLOCKER_TYPES)}"
                ),
                raw_text=call_result.text,
            )
        blocker_type = BlockerType(blocker_type_raw)

        alternatives_raw = require_list(parsed, "considered_alternative_types", agent_id=AGENT_ID)
        alternatives: list[BlockerType] = []
        for item in alternatives_raw:
            if not isinstance(item, str) or item not in _VALID_BLOCKER_TYPES:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"unrecognised considered_alternative_types entry {item!r}",
                    raw_text=call_result.text,
                )
            if item == blocker_type_raw:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason="considered_alternative_types must not repeat the chosen blocker_type",
                    raw_text=call_result.text,
                )
            alternatives.append(BlockerType(item))

        diagnosis_text = require_str(parsed, "diagnosis_text", agent_id=AGENT_ID)
        if not diagnosis_text.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="diagnosis_text must not be blank", raw_text=call_result.text
            )

        evidence_raw = require_list(parsed, "evidence", agent_id=AGENT_ID)
        evidence = tuple(item for item in evidence_raw if isinstance(item, str))

        prior = request.prior_diagnosis
        is_rediagnosis = prior is not None
        superseded_type = (
            prior.blocker_type if (prior is not None and prior.blocker_type != blocker_type) else None
        )

        return BlockerDiagnosis(
            obligation_id=request.obligation_id,
            person_id=request.person_id,
            blocker_type=blocker_type,
            diagnosis_text=diagnosis_text,
            evidence=evidence,
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            considered_alternative_types=tuple(alternatives),
            is_rediagnosis=is_rediagnosis,
            superseded_diagnosis_type=superseded_type,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            diagnosed_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "BlockerDiagnosisAgent"]

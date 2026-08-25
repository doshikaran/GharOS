"""A57 — Confidence Arbiter (spec §15.12, PHASES.md Phase 5).

*Responsibility:* evaluate every `ProposedAction` against thresholds and
decide execute / approve / escalate / discard. **The only path to
action** — nothing downstream of this module ever routes a proposal to
execution without passing through `ConfidenceArbiter.evaluate` first.

*Model tier:* `ModelTier.DETERMINISTIC` for the policy layer — tier
classification (`app.reasoning.risk_policy.classify_risk_tier`), the
hard-constraint floor (`apply_hard_constraint_floor`), and the confidence
floor lookup (`confidence_floor`) are all plain code, no LLM call — plus
`ModelTier.PRO` for the one case spec §15.12 explicitly names:
**"Pro-tier for borderline."** A clearly-above-floor or clearly-below-floor
confidence never reaches a model call (spec §21.1 cost discipline) — only
a score within `_BORDERLINE_BAND` of its tier's floor does.

*Forbidden:* discarding a genuinely uncitable/unfounded proposal by
silently executing it anyway; calling Pro-tier on a clear-cut case;
constructing a `contracts.actions.Action` directly (that is
`app.arbitration.actions`'/`approval_gate.py`'s job, once *this* module
has decided the proposal should proceed).

Composes directly with E2's Phase 5 deliverable,
`app.reasoning.risk_policy` — see that module's own docstring for why the
*classification* policy lives there (E2, no tool import) while the
*decision* (execute/approve/escalate/discard) lives here (E3, the only
module with an import path to actually acting on that decision).
"""

from __future__ import annotations

import json
import re

import structlog
from contracts.actions import EvidenceBundle, RiskTier, downgrade_tier
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.risk_policy import apply_hard_constraint_floor, classify_risk_tier, confidence_floor

from .types import ArbiterDecision, ArbiterResult, ProposedAction

AGENT_ID = AgentId("A57")

logger = structlog.get_logger(__name__)

_ABSOLUTE_DISCARD_FLOOR = 0.20
"""Below this, confidence is discarded outright regardless of tier — not
merely downgraded. Spec §19.2 gives three distinct options for a
below-threshold action ("downgrade tier, escalate, or discard"); a score
this low means the underlying claim is unlikely to be real at all, so
"discard" is the only honest option — downgrading a near-baseless claim to
a stricter tier would still eventually present or act on something not
worth acting on. Deliberately well below every tier's own
`confidence_floor` (R0's, the lowest, is 0.50) so it only fires for
genuinely bad evidence, never as a disguised second floor for R0."""

_BORDERLINE_BAND = 0.05
"""How close to a tier's floor counts as "borderline" (spec §15.12:
"Pro-tier for borderline"). A score within this band of the floor gets one
real Pro-tier adjudication call; anything further below is treated as
clearly-below (deterministic downgrade, no model call — cost discipline,
spec §21.1); anything at or above the floor is clearly-above (no model
call either). Symmetric, small, and documented rather than tuned per
tier — the floors themselves already vary the bar per tier."""

_BORDERLINE_PROMPT = """You are the Confidence Arbiter for a household operating system, deciding whether \
a proposed action's confidence score — though marginally under its risk tier's minimum floor — \
genuinely reflects well-corroborated evidence that should be allowed to proceed at this tier, or \
should be treated as below threshold.

Action type: {action_type}
Risk tier under consideration: {tier}
Confidence score: {confidence:.3f}
Tier's minimum confidence floor: {floor:.3f}
Reasoning given by the proposing agent: {reasoning}
Evidence consulted: {evidence}
Consequence if this action is wrong: {consequence_if_wrong}

Respond with a single JSON object and nothing else:
{{"proceed": true or false, "explanation": "one or two sentences"}}

"proceed": true means the evidence genuinely supports this tier despite the raw score sitting \
marginally under the floor (e.g. the score understates strong, well-corroborated evidence). \
"proceed": false means treat this as genuinely below threshold — do not let a borderline score \
default to "proceed" without a specific reason grounded in the evidence given above."""

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _parse_borderline_verdict(*, action_type: str, text: str) -> bool:
    """Parses the Pro-tier borderline-adjudication response.

    Returns:
        `True` ("proceed" — treat the score as clearing the floor),
        `False` otherwise.

    A malformed response is treated as `False` (never silently "proceed"
    on an uninterpretable model response — spec §19.2's "never silently
    proceed" applies to interpretation failures too, not just to low
    scores), logged so the gap is visible rather than hidden.
    """
    candidate = text.strip()
    fence_match = _JSON_FENCE_PATTERN.match(candidate)
    if fence_match is not None:
        candidate = fence_match.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning(
            "arbitration.confidence_arbiter.borderline_response_malformed",
            action_type=action_type,
            raw_text=text,
        )
        return False
    if not isinstance(parsed, dict) or not isinstance(parsed.get("proceed"), bool):
        logger.warning(
            "arbitration.confidence_arbiter.borderline_response_malformed",
            action_type=action_type,
            raw_text=text,
        )
        return False
    return bool(parsed["proceed"])


def _decision_for_tier(tier: RiskTier) -> ArbiterDecision:
    if tier in (RiskTier.R0_SILENT, RiskTier.R1_NOTIFY):
        return ArbiterDecision.EXECUTE
    if tier in (RiskTier.R2_APPROVE, RiskTier.R3_EXPLICIT_APPROVE):
        return ArbiterDecision.APPROVE
    return ArbiterDecision.ESCALATE  # R4


def _evidence_bundle_for(proposed: ProposedAction, *, confidence: float) -> EvidenceBundle:
    return EvidenceBundle(
        proposed_action=f"{proposed.action_type} ({proposed.entity_id}, cycle {proposed.cycle})",
        reasoning=proposed.reasoning,
        evidence_consulted=proposed.evidence_consulted,
        confidence=confidence,
        consequence_if_wrong=proposed.consequence_if_wrong,
    )


class ConfidenceArbiter:
    """A57. Dependency-injected on a `GeminiClient` for the borderline
    Pro-tier path only — every other decision is pure code.

    **Production wiring note (see this phase's final report):** a live
    Pro-tier call here requires `AgentId("A57")` to be present in
    `app.reasoning.model_router.PRO_TIER_ALLOWLIST` — that module is
    E2-owned (`backend/app/reasoning/`) and is not edited by this package.
    Until "A57" is added there, a real borderline call raises
    `app.reasoning.errors.ProTierNotAllowlisted`; this class's own tests
    inject a `GeminiClient` whose underlying `ModelRouter` has the
    allowlist patched for the duration of the test, proving this
    class's *own* logic correct independent of that cross-role wiring gap.
    """

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def evaluate(self, proposed: ProposedAction) -> ArbiterResult:
        """Decides execute / approve / escalate / discard for `proposed`.

        Raises:
            app.reasoning.errors.ActionTypeNotClassified: `proposed.
                action_type` has no entry in `risk_policy`'s classification
                table — propagates unchanged; the caller must route this
                to escalation rather than guess (per that error's own
                docstring), never treat it as EXECUTE/DISCARD.
        """
        base_tier = classify_risk_tier(proposed.action_type)
        tier = apply_hard_constraint_floor(
            base_tier, hard_constraint_involved=proposed.involves_hard_constraint
        )
        confidence = proposed.confidence

        if confidence < _ABSOLUTE_DISCARD_FLOOR:
            return self._result(
                proposed,
                ArbiterDecision.DISCARD,
                tier,
                confidence,
                escalated_to_pro=False,
                discard_reason=(
                    f"confidence {confidence:.2f} is below the absolute discard floor "
                    f"{_ABSOLUTE_DISCARD_FLOOR:.2f} — too unreliable to act on or present, per spec "
                    "§19.2's 'downgrade tier, escalate, or discard'"
                ),
            )

        floor = confidence_floor(tier)
        escalated_to_pro = False

        if confidence < floor:
            if floor - confidence <= _BORDERLINE_BAND:
                escalated_to_pro = True
                proceed = self._adjudicate_borderline(proposed, tier=tier, confidence=confidence, floor=floor)
            else:
                proceed = False  # clearly below — deterministic, no model call (cost discipline)

            if not proceed:
                if tier is RiskTier.R4_ESCALATE_ONLY:
                    return self._result(
                        proposed,
                        ArbiterDecision.DISCARD,
                        tier,
                        confidence,
                        escalated_to_pro,
                        discard_reason=(
                            f"confidence {confidence:.2f} is below R4's floor {floor:.2f} — R4 has no "
                            "stricter tier to downgrade to, so per risk_policy.confidence_floor's own "
                            "documented rule ('gates whether a candidate option is even presented'), "
                            "this candidate is not presented at all rather than escalated anyway"
                        ),
                    )
                tier = downgrade_tier(tier)

        decision = _decision_for_tier(tier)
        return self._result(proposed, decision, tier, confidence, escalated_to_pro, discard_reason=None)

    def _adjudicate_borderline(
        self, proposed: ProposedAction, *, tier: RiskTier, confidence: float, floor: float
    ) -> bool:
        prompt = _BORDERLINE_PROMPT.format(
            action_type=proposed.action_type,
            tier=tier.value,
            confidence=confidence,
            floor=floor,
            reasoning=proposed.reasoning,
            evidence=", ".join(proposed.evidence_consulted) or "(none listed)",
            consequence_if_wrong=proposed.consequence_if_wrong,
        )
        try:
            call_result = self._gemini_client.generate_structured(
                agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=prompt
            )
        except GeminiCallFailed as exc:
            # A failed borderline-adjudication call is never silently
            # reinterpreted as "proceed" — safety invariant #7's logic
            # applies here too: a failure never fabricates a permissive
            # outcome. Treat exactly like an unparseable response.
            logger.warning(
                "arbitration.confidence_arbiter.borderline_call_failed",
                action_type=proposed.action_type,
                reason=str(exc),
            )
            return False
        return _parse_borderline_verdict(action_type=proposed.action_type, text=call_result.text)

    def _result(
        self,
        proposed: ProposedAction,
        decision: ArbiterDecision,
        tier: RiskTier,
        confidence: float,
        escalated_to_pro: bool,
        discard_reason: str | None,
    ) -> ArbiterResult:
        logger.info(
            "arbitration.confidence_arbiter.decided",
            action_type=proposed.action_type,
            entity_id=proposed.entity_id,
            decision=decision.value,
            final_risk_tier=tier.value,
            confidence=confidence,
            escalated_to_pro=escalated_to_pro,
        )
        return ArbiterResult(
            proposed_action=proposed,
            decision=decision,
            final_risk_tier=tier,
            confidence=confidence,
            evidence_bundle=_evidence_bundle_for(proposed, confidence=confidence),
            escalated_to_pro=escalated_to_pro,
            discard_reason=discard_reason,
        )


__all__ = ["AGENT_ID", "ConfidenceArbiter"]

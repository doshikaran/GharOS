"""A55 — Confirmation Verifier (spec §13.2 Step 6, §13.6, §15.10,
PHASES.md Gate 10) — E2's half of `backend/app/agents/concierge/`.

*Responsibility:* "cross-check the outcome against what was requested
before anything is recorded" (spec §15.10 A55). This is Gate 10's single
most safety-critical agent: "unverified outcome never recorded — proven
by test."

**Two-layer design, deliberately asymmetric:**

1. **Structural check — deterministic, no model call.**
   `verification.verify_call_outcome` compares the real `types.
   CallOutcomeReport` against the real `types.CallBrief` it was
   authorised under: correct provider, correct date range, an authorised
   slot, disclosure given, no unresolved out-of-bounds event. This alone
   already catches "wrong date", "wrong slot", and
   `disclosure_given=False` — spec §13.2 Step 6's named discrepancy
   cases.
2. **Semantic check — Pro-tier, and ONLY EVER NARROWING.** `CallBrief`/
   `CallOutcomeReport` have no structured "service type" field — only
   `CallOutcomeReport.claimed_outcome_summary`, free text. Catching a
   "wrong service" discrepancy (spec §13.2 Step 6's other named case;
   e.g. the call summary describes a haircut when the objective was a
   dental cleaning) genuinely needs language judgment, so a Pro-tier
   call runs **only when the structural check already passed** (cost
   discipline: nothing to narrate at length when the structural check
   already failed — mirrors `app.agents.fair_allocator.
   load_monitor_agent`'s "nothing to narrate" precedent) and can only
   turn a structural pass into a final fail, never the reverse.

**The safety-critical guarantee is structural, not conventional:** the
final `VerificationResult.verified` this agent returns traces back
*only* to (a) `VerificationVerdict.verified` from step 1, AND (b), when
step 1 passed, the step-2 model's `semantically_plausible` boolean. At
no point in this module's code is a `"verified"` key ever read out of a
parsed Gemini JSON response — the step-2 prompt does not even ask the
model for one, and even if a model response smuggled one in anyway
(prompt injection, confusion, or an adversarial test), there is no call
in this file to `parsed["verified"]` or `require_bool(parsed,
"verified", ...)` for that value to reach. See
`test_confirmation_verifier_agent.py`'s adversarial tests for the direct
proof, including one where the fake model response embeds a bogus
`"verified": true` key alongside a genuine `"semantically_plausible":
false` and the final result is still `verified=False`.

*Forbidden:* **recording an unverified booking.** This agent holds no
`GraphWriter` and no write tool of any kind — there is no import in this
module of `app.tools.graph_write_tool`, `app.tools.registry`, or
`app.arbitration` at all (see `test_confirmation_verifier_agent.py`'s
AST-based forbidden-import test, mirroring `test_blocker_diagnosis_
agent.py`'s established pattern). The actual graph write
(`app.tools.booking_write_tool.verified_booking_from_verification`, E3's
territory) is a separate, downstream step this module has no path to at
all — it is gated on this agent's `VerificationResult.verified` being
`True` by that tool's own construction, never by this module reaching
into the graph itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import CallBrief, CallOutcomeReport, VerificationResult
from .verification import verify_call_outcome

AGENT_ID = AgentId("A55")


class ConfirmationVerifierAgent:
    """A55 Confirmation Verifier. Dependency-injected on a `GeminiClient`
    only — no `GraphWriter`, no write tool, no approval-gate import of
    any kind (see module docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def verify(self, *, brief: CallBrief, report: CallOutcomeReport) -> VerificationResult:
        """Verifies `report` against exactly what `brief` authorised.

        Args:
            brief: the real `CallBrief` this call was authorised under.
            report: E3's A54 real, claimed outcome.

        Returns:
            A `VerificationResult`. `verified=True` only when both the
            deterministic structural check AND (when reached) the
            Pro-tier semantic cross-check agree — see module docstring.

        Raises:
            errors.ModelResponseMalformed: the semantic cross-check
                call's response could not be parsed as the expected JSON
                shape. Never raised when the structural check alone
                already failed (no such call is made in that case).
        """
        verdict = verify_call_outcome(brief=brief, report=report)
        now = datetime.now(UTC)

        if not verdict.verified:
            return VerificationResult(
                call_id=report.call_id,
                target_provider_id=report.target_provider_id,
                verified=False,
                discrepancies=verdict.discrepancies,
                requires_human_callback=verdict.requires_human_callback,
                explanation="; ".join(verdict.discrepancies),
                confidence=1.0,
                model_tier="deterministic",
                prompt_version="n/a",
                invocation_id=uuid.uuid4().hex,
                verified_at=now,
            )

        prompt = load_prompt("A55")
        rendered = prompt.text.format(
            objective=brief.objective,
            claimed_slot=report.claimed_slot.isoformat() if report.claimed_slot is not None else "(none)",
            claimed_outcome_summary=report.claimed_outcome_summary,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        # Deliberately reads ONLY `semantically_plausible`, `explanation`,
        # and `confidence` — see module docstring for why `parsed` is
        # never consulted for a "verified" key of any kind.
        semantically_plausible = require_bool(parsed, "semantically_plausible", agent_id=AGENT_ID)
        explanation = require_str(parsed, "explanation", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        if not semantically_plausible:
            return VerificationResult(
                call_id=report.call_id,
                target_provider_id=report.target_provider_id,
                verified=False,
                discrepancies=(f"semantic mismatch: {explanation}",),
                requires_human_callback=True,
                explanation=explanation,
                confidence=confidence,
                model_tier="pro",
                prompt_version=prompt.version,
                invocation_id=uuid.uuid4().hex,
                verified_at=now,
            )

        return VerificationResult(
            call_id=report.call_id,
            target_provider_id=report.target_provider_id,
            verified=True,
            discrepancies=(),
            requires_human_callback=False,
            explanation=explanation,
            confidence=confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            verified_at=now,
        )


__all__ = ["AGENT_ID", "ConfirmationVerifierAgent"]

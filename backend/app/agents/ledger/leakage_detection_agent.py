"""A29 — Leakage Detection Agent (spec §10.3C, §15.7).

*Responsibility:* the "worth reasoning" step — is this RECURRING_COMMITMENT
still wanted, given real usage signals and the household's actual current
priorities? Spec's own framing is the whole point of this agent existing
as an LLM call rather than a cron job: "a price rise on a daily-used
service is fine; the same rise on one last touched in March is not."

*Model tier:* Pro-tier — this is a genuine, per-item reasoned judgment
against real signals, **never a rule-based cutoff** (e.g. "not used in 60
days" alone). This module computes the deterministic signals
(`days_since_last_used`, `price_change_pct`) itself — arithmetic never
belongs in a model call — but the verdict itself always comes from the
model's judgment over those signals plus the household's real priorities
text, never from a threshold check in this module.

*Forbidden:* **cancelling anything.** This agent holds no tool at all —
no `ToolRegistry`, no `GraphWriter`/`GraphReader` import, nothing that
could act. `LeakageFinding` (this module's entire output shape) has no
field that could represent an action taken; it is the caller's job (A30
Recovery Drafting, itself draft-only) to do anything with a `"leakage"`
verdict.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_str
from .types import LeakageAssessmentRequest, LeakageFinding, LeakageVerdict

AGENT_ID = AgentId("A29")

logger = structlog.get_logger(__name__)

_VALID_VERDICTS: frozenset[str] = frozenset({"leakage", "worth_keeping", "ambiguous"})


def _days_since_last_used(request: LeakageAssessmentRequest) -> int | None:
    if request.last_used_at is None:
        return None
    return max(0, (request.now - request.last_used_at).days)


def _price_change_pct(request: LeakageAssessmentRequest) -> float | None:
    if len(request.price_history) < 2:
        return None
    (_, oldest_price), (_, newest_price) = request.price_history[0], request.price_history[-1]
    if oldest_price == 0:
        return None
    return (newest_price - oldest_price) / oldest_price * 100.0


def _price_history_block(price_history: tuple[tuple[datetime, float], ...]) -> str:
    if not price_history:
        return "(no price history recorded)"
    return "\n".join(f"- {when}: {price:.2f}" for when, price in price_history)


class LeakageDetectionAgent:
    """A29 Leakage Detection. Dependency-injected on a `GeminiClient` only
    — deliberately no tool of any kind (see this module's docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def assess(self, request: LeakageAssessmentRequest) -> LeakageFinding:
        """Judges whether `request`'s commitment is leakage.

        Args:
            request: the commitment plus the usage/price signals and
                household-priorities context to reason against.

        Returns:
            A `LeakageFinding` — `verdict` always comes from the model's
            real judgment over the signals, never a threshold this module
            applies itself.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, or returned a verdict
                outside `_VALID_VERDICTS`.
        """
        days_since_used = _days_since_last_used(request)
        change_pct = _price_change_pct(request)

        prompt = load_prompt("A29")
        rendered = prompt.text.format(
            commitment_label=request.label,
            commitment_counterparty=request.counterparty,
            commitment_amount=f"{request.amount:.2f}",
            commitment_cadence=request.cadence,
            commitment_status=request.status,
            price_history_block=_price_history_block(request.price_history),
            price_change_pct=(f"{change_pct:+.1f}%" if change_pct is not None else "not enough history"),
            last_used_at=(
                request.last_used_at.isoformat() if request.last_used_at is not None else "never recorded"
            ),
            days_since_last_used=(str(days_since_used) if days_since_used is not None else "unknown"),
            household_priorities=request.household_priorities,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        verdict = require_str(parsed, "verdict", agent_id=AGENT_ID)
        if verdict not in _VALID_VERDICTS:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason=f"unrecognised verdict {verdict!r}", raw_text=call_result.text
            )
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        evidence: dict[str, str] = {
            "last_used_at": (
                request.last_used_at.isoformat() if request.last_used_at is not None else "never"
            ),
            "days_since_last_used": (str(days_since_used) if days_since_used is not None else "unknown"),
        }
        if change_pct is not None:
            evidence["price_change_pct"] = f"{change_pct:+.1f}%"

        logger.info(
            "agents.ledger.a29.completed",
            commitment_id=str(request.commitment_id),
            verdict=verdict,
            days_since_last_used=days_since_used,
        )
        return LeakageFinding(
            commitment_id=request.commitment_id,
            verdict=cast_verdict(verdict),
            reasoning=reasoning,
            days_since_last_used=days_since_used,
            price_change_pct=change_pct,
            confidence=confidence,
            evidence=evidence,
        )


def cast_verdict(verdict: str) -> LeakageVerdict:
    """Narrows a validated (member-of-`_VALID_VERDICTS`) string to the
    `LeakageVerdict` literal — a tiny helper so the one runtime check in
    `assess` above is also what satisfies the static type checker, rather
    than a bare `# type: ignore` at the construction site."""
    if verdict == "leakage":
        return "leakage"
    if verdict == "worth_keeping":
        return "worth_keeping"
    return "ambiguous"


__all__ = ["AGENT_ID", "LeakageDetectionAgent"]

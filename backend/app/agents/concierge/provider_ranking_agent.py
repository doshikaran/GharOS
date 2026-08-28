"""A52 — Provider Ranking (spec §13.2 Step 3, §15.10, ADR-016) — E2's
half of `backend/app/agents/concierge/`.

*Responsibility:* "multi-factor, transparent ranking including prior
household experience" (spec §15.10 A52). The actual ranking — order,
score, per-provider reasons, whether a provider was demoted for a real
no-show — is entirely `ranking.rank_candidates`'s deterministic,
no-model-call output; see that module's docstring for why. This agent's
only real job is writing a short, natural-language narrative gloss on
top of that already-final order (Gate 10: "the user sees why #1 is #1"
— the deterministic `RankedProvider.reasons`/`score_components` already
satisfy this on their own; `narrative` is a readability layer, not the
safety-relevant explanation).

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) per spec
§15.10's own roster entry.

*Forbidden:* **opaque ranking.** Structurally enforced: `rank`, `score`,
and `demoted_for_reliability` on every `types.RankedProvider` this agent
returns come only from `ranking.rank_candidates` — this module's prompt
explicitly tells the model "you do not re-rank anything," and the code
never reads a rank/order/score field back out of the model's parsed JSON
at all (only `narrative` and `confidence` are read) — there is no code
path by which a model response could reorder the list this agent
returns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_str
from .ranking import rank_candidates
from .types import ProviderCandidate, ProviderRankingResult, RankedProvider, RankingContext

AGENT_ID = AgentId("A52")


def _ranked_block(ranked: tuple[RankedProvider, ...]) -> str:
    lines = []
    for entry in ranked:
        reasons = "; ".join(entry.reasons)
        components = ", ".join(f"{key}={value:.2f}" for key, value in sorted(entry.score_components.items()))
        demoted_note = " [DEMOTED for prior reliability problem]" if entry.demoted_for_reliability else ""
        lines.append(
            f"#{entry.rank} {entry.name} (score={entry.score:.2f}){demoted_note}: {reasons} ({components})"
        )
    return "\n".join(lines)


class ProviderRankingAgent:
    """A52 Provider Ranking. Dependency-injected on a `GeminiClient`
    only — no `GraphReader` of its own (`types.RankingContext` arrives
    pre-resolved on the caller's side, via `context.
    resolve_reliability_signal` per candidate)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def rank(
        self,
        *,
        candidates: tuple[ProviderCandidate, ...],
        context: RankingContext,
        service_category: str,
        person_id: NodeId,
    ) -> ProviderRankingResult:
        """Ranks `candidates` and narrates the result.

        Args:
            candidates: E3's A51 real discovered/known providers.
            context: real, pre-resolved scoring context.
            service_category: e.g. `"dental"`.
            person_id: who the service is for.

        Returns:
            A `ProviderRankingResult` whose `ranked` order is always
            exactly `ranking.rank_candidates`'s own output order.

        Raises:
            errors.ModelResponseMalformed: the narrative call's response
                could not be parsed as the expected JSON shape.
        """
        ranked = rank_candidates(candidates, context)
        now = datetime.now(UTC)

        if not ranked:
            return ProviderRankingResult(
                service_category=service_category,
                person_id=person_id,
                ranked=(),
                urgency=context.urgency,
                narrative="No candidate providers were found for this request.",
                confidence=0.0,
                model_tier="deterministic",
                prompt_version="n/a",
                invocation_id=uuid.uuid4().hex,
                ranked_at=now,
            )

        prompt = load_prompt("A52")
        rendered = prompt.text.format(
            service_category=service_category,
            urgency=context.urgency.value,
            ranked_block=_ranked_block(ranked),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        narrative = require_str(parsed, "narrative", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        return ProviderRankingResult(
            service_category=service_category,
            person_id=person_id,
            ranked=ranked,
            urgency=context.urgency,
            narrative=narrative,
            confidence=confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            ranked_at=now,
        )


__all__ = ["AGENT_ID", "ProviderRankingAgent"]

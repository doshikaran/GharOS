"""A21 — Load Monitor (spec §8.4, §15.8).

*Responsibility:* continuous fairness-*over-time* tracking — detects
creeping imbalance between formal re-allocations, using real completed-
load evidence (`contracts.repositories.GraphReader.load`), never a
guessed one.

*Model tier:* Flash. The verdict itself is a deterministic threshold
comparison against real, already-computed numbers (this person's expected
share of total cost from the last `FairAllocationResult.person_total_cost`
versus their real observed share of completed household load) — a fixed
numeric threshold is the evidence-backed, non-guessed way to decide
"is this drift worth surfacing," not something an LLM should be asked to
eyeball. Flash is used only to **narrate** a real, already-decided
`"creeping_imbalance"` finding in plain language for the household to
read — never to compute or alter the numbers themselves, and never called
at all for a `"balanced"` or `"insufficient_data"` verdict (cost
discipline: nothing to narrate at length when there is no finding).
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_str
from .types import LoadDriftCheckRequest, LoadImbalanceFinding

AGENT_ID = AgentId("A21")

_IMBALANCE_DRIFT_THRESHOLD = 0.15
"""A person's observed share of completed load diverging from their
expected share by more than this (in either direction) is a real,
evidence-backed imbalance worth surfacing — a fixed, documented,
revisitable constant (mirrors `app.agents.ledger.reconciliation_agent.
_MISMATCH_ABS_TOLERANCE`'s same role: a real product tunable, not a
guessed one)."""


class LoadMonitorAgent:
    """A21 Load Monitor. Dependency-injected on a `GeminiClient` only —
    read-only by nature (it consumes already-resolved numbers; graph
    reads themselves are the caller's job via `context.household_total_load`
    and `contracts.repositories.GraphReader.load`)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def check_drift(self, request: LoadDriftCheckRequest) -> LoadImbalanceFinding:
        """Checks one person's real load drift against their expected
        share.

        Args:
            request: the real expected share, observed load, and
                household-total observed load for this person's window.

        Returns:
            A `LoadImbalanceFinding` — `verdict` always comes from a real
            threshold comparison over the given numbers, never a guess.

        Raises:
            errors.ModelResponseMalformed: the narration call's response
                could not be parsed as the expected JSON shape (only
                reachable for a `"creeping_imbalance"` verdict).
        """
        if request.household_total_observed_load <= 0.0:
            return LoadImbalanceFinding(
                person_id=request.person_id,
                expected_share=request.expected_share_of_total_cost,
                observed_share=None,
                drift=None,
                verdict="insufficient_data",
                reasoning=(
                    "no observed household load at all this window — cannot compute a real "
                    "observed share, so no imbalance can be claimed."
                ),
                confidence=1.0,
                model_tier="deterministic",
            )

        observed_share = request.observed_load / request.household_total_observed_load
        drift = observed_share - request.expected_share_of_total_cost

        if abs(drift) <= _IMBALANCE_DRIFT_THRESHOLD:
            return LoadImbalanceFinding(
                person_id=request.person_id,
                expected_share=request.expected_share_of_total_cost,
                observed_share=observed_share,
                drift=drift,
                verdict="balanced",
                reasoning=(
                    f"observed share ({observed_share:.2f}) is within {_IMBALANCE_DRIFT_THRESHOLD:.2f} "
                    f"of the expected share ({request.expected_share_of_total_cost:.2f}) — no action needed."
                ),
                confidence=1.0,
                model_tier="deterministic",
            )

        reasoning = self._narrate(
            person_id=str(request.person_id),
            expected_share=request.expected_share_of_total_cost,
            observed_share=observed_share,
            drift=drift,
        )
        return LoadImbalanceFinding(
            person_id=request.person_id,
            expected_share=request.expected_share_of_total_cost,
            observed_share=observed_share,
            drift=drift,
            verdict="creeping_imbalance",
            reasoning=reasoning,
            confidence=1.0,
            model_tier="flash",
        )

    def _narrate(self, *, person_id: str, expected_share: float, observed_share: float, drift: float) -> str:
        prompt = load_prompt("A21")
        rendered = prompt.text.format(
            person_id=person_id,
            expected_share=f"{expected_share:.2f}",
            observed_share=f"{observed_share:.2f}",
            drift=f"{drift:+.2f}",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        return require_str(parsed, "reasoning", agent_id=AGENT_ID)


__all__ = ["AGENT_ID", "LoadMonitorAgent"]

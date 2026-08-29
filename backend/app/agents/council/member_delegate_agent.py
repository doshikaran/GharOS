"""A47 — Member Delegate (spec §12.3 Phase 4, §12.4, §15.9,
PHASES.md Phase 12, ADR-019 Decision 4) — E2's
`backend/app/agents/council/`.

*Responsibility:* one instance per convened household member. Scores each
surviving candidate branch against **that one person's own** real
valuation, producing a **new, decision-scoped** `ValuationProfile`
(`costs` keyed by `str(branch_id)`) — never a reuse of a Fair Allocator
chore-era profile (ADR-019 Decision 4: a person's cost for "doing the
dishes" has no relationship to their cost for "which car to buy").

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — turning one
real person's behavioural signals into a real cardinal cost per option is
judgment, mirroring A18 Valuation Extraction's identical discipline one
phase earlier.

**Structurally cannot speak for anyone else (spec §15.9 A47 forbidden):**
the constructor takes exactly one `person_id`; `types.
DelegateScoringRequest` carries **no `person_id` field at all** — there is
no parameter anywhere through which a caller could ask one instance to
score on behalf of a different person (see that dataclass's own
docstring). Every `DelegateScoring`/`ValuationProfile` this instance ever
produces carries `self._person_id`, never a value derived from the
request.

**Never invents a preference the elicitation doesn't support (spec §15.9
A47 forbidden) — sparse by omission, exactly A18's own discipline (Phase
8):** a returned cost below `_COST_CONFIDENCE_FLOOR`, or for a branch id
the request never named, is dropped before it ever reaches the written
`ValuationProfile.costs` — never fabricated as `0.0`.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Derivation, NodeId, Provenance, ValuationProfile

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from . import context
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_list, require_str
from .types import DelegateScoring, DelegateScoringRequest

AGENT_ID = AgentId("A47")

_COST_CONFIDENCE_FLOOR = 0.5
"""Mirrors `app.agents.fair_allocator.valuation_extraction_agent`'s own
named floor — a returned cost the model itself was not confident about is
never written, exactly A18's "sparse matrix -> request coverage, never
fabricate values" discipline, applied to a decision-scoped matrix instead
of a chore-era one."""


def _signals_block(signals: tuple[str, ...]) -> str:
    if not signals:
        return "(no known behavioural preference signals on file for this person)"
    return "\n".join(f"- {signal}" for signal in signals)


class MemberDelegateAgent:
    """A47 Member Delegate — one instance per convened household member.
    Dependency-injected on a `GeminiClient` and the one `person_id` this
    instance is permanently bound to; holds no `GraphReader` of any kind
    (mirrors A35 Decision Framing's "pre-resolved by the caller"
    precedent — real behavioural signals are assembled by the pipeline's
    caller, not read directly by this agent)."""

    def __init__(self, *, gemini_client: GeminiClient, person_id: NodeId) -> None:
        self._gemini_client = gemini_client
        self._person_id = person_id

    @property
    def person_id(self) -> NodeId:
        """Exposed for the same adversarial-proof reason other agents'
        bound state is — a test can assert which person this instance
        speaks for without running it."""
        return self._person_id

    def score(self, request: DelegateScoringRequest) -> DelegateScoring:
        """Scores `request.framing`'s real candidate branches from
        `self.person_id`'s own real behavioural signals.

        Args:
            request: the decision's basic framing (real surviving
                candidate branches only — the caller is responsible for
                excluding anything a specialist already eliminated) plus
                this one person's own real, pre-resolved preference
                signals.

        Returns:
            A `DelegateScoring` for `self.person_id`. `valuation_profile.
            costs` is sparse by omission — a branch this instance was not
            confidently able to price is simply absent.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, or `reasoning` was
                blank.
        """
        framing = request.framing
        prompt = load_prompt("A47")
        rendered = prompt.text.format(
            question=framing.question,
            trigger=framing.trigger,
            branches_block=context.branches_block(framing),
            preference_signals_block=_signals_block(request.known_preference_signals),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        if not reasoning.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="reasoning must not be blank", raw_text=call_result.text
            )

        real_branch_ids = {str(branch.branch_id) for branch in framing.candidate_branches}
        raw_items = require_list(parsed, "branch_costs", agent_id=AGENT_ID)
        costs: dict[str, float] = {}
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            branch_id = require_str(raw_item, "branch_id", agent_id=AGENT_ID)
            if branch_id not in real_branch_ids:
                continue  # never propagate a hallucinated branch id
            cost = require_float(raw_item, "cost", agent_id=AGENT_ID)
            confidence = require_float(raw_item, "confidence", agent_id=AGENT_ID, default=0.0)
            if confidence < _COST_CONFIDENCE_FLOOR or not math.isfinite(cost) or cost < 0:
                continue  # sparse by omission — never fabricate, never write a low-confidence guess
            costs[branch_id] = cost

        valuation_profile = ValuationProfile(
            id=NodeId(f"valuation-profile:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=1.0 if costs else 0.0,
                deriving_agent=AGENT_ID,
                created_at=datetime.now(UTC),
            ),
            person_id=self._person_id,
            costs=costs,
            elicitation_method=request.elicitation_method,
        )
        return DelegateScoring(
            person_id=self._person_id, valuation_profile=valuation_profile, reasoning=reasoning
        )


__all__ = ["AGENT_ID", "MemberDelegateAgent"]

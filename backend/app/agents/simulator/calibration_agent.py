"""A39 — Calibration (spec §11.5, §15.8, PHASES.md Phase 11, ADR-017) —
E2's `backend/app/agents/simulator/`.

*Responsibility:* narrate this household's own real historical variance
for one decision category (`Outcome.attribution_tags` value, e.g.
`"relocation"`) — used by forward mode (per-branch calibration evidence
feeding A40's brief) and reused unchanged by backward mode (A40's
`synthesize_backward` narrates a predicted failure point from this same
agent's `ranked_outcomes`, per ADR-017 decision 3: "backward mode is a
second entry point on A35/A39/A40, not a seventh agent").

**Never computes statistics itself.** Every number here comes from
`app.solvers.calibration_stats.compute_calibration`/`rank_by_absolute_
variance` (E1) — this module's own Gemini call only narrates what those
functions already produced, in plain language, never inventing precision
they didn't produce (spec §11.5/§15.8 A39: "statistics delegated to a
tool").

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) whenever at
least one real `Outcome` exists for the tag, thin or not — **deterministic
(no model call at all)** when there is zero history, mirroring
`app.agents.fair_allocator.load_monitor_agent`'s established "nothing to
narrate" precedent: there is nothing beyond the tool's own honest
zero-count note to narrate at length. When the real sample is non-zero but
still thin (`CalibrationEstimate.is_thin_history`), `estimate.note` is
guaranteed, structurally (not just by prompt instruction), to appear
verbatim in the returned `narrative` — see `_ensure_note_present`.

`outcome_variance` is a Phase 11 addition to `GraphReader` (ADR-017) not
yet in `GraphReadTool`'s dispatch table — this agent holds a bare
`GraphReader` directly, T0-equivalent, mirroring `PathSimulatorAgent`'s
identical precedent for `blast_radius_multi`.

*Forbidden:* computing or overriding a statistic itself; fabricating
confidence when the real sample is thin or absent (spec §11.5's named
failure mode: "Cold start... be honest").
"""

from __future__ import annotations

from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from contracts.repositories import GraphReader

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.calibration_stats import RankedOutcome, compute_calibration, rank_by_absolute_variance
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_str
from .types import CalibrationNarration

AGENT_ID = AgentId("A39")

_DEFAULT_TOP_N = 3
"""How many `RankedOutcome`s `narrate()` surfaces by default — matches
`rank_by_absolute_variance`'s own default, kept as this module's own named
constant rather than a bare literal at the call site."""


def _outcome_lines(tag: str, ranked_outcomes: tuple[RankedOutcome, ...]) -> str:
    if not ranked_outcomes:
        return f"(no past outcomes tagged {tag!r} with a settled variance)"
    lines = [
        f"- {ranked.outcome.id}: predicted {ranked.outcome.predicted!r}, "
        f"actual {ranked.outcome.actual!r}, variance {ranked.outcome.variance:+.4g}"
        for ranked in ranked_outcomes
    ]
    return "\n".join(lines)


def _ensure_note_present(*, narrative: str, note: str) -> str:
    """Structural guarantee (not just a prompt instruction) that a
    thin-history `estimate.note` appears verbatim in the returned
    narrative, regardless of what the model itself produced (spec §11.5:
    "insufficient history -> say so, never produce false precision")."""
    if note in narrative:
        return narrative
    return f"{narrative} {note}"


class CalibrationAgent:
    """A39 Calibration. Dependency-injected on a `GeminiClient` and a bare
    `GraphReader` — no write tool of any kind (this agent only narrates,
    it never writes to the graph)."""

    def __init__(self, *, gemini_client: GeminiClient, graph_reader: GraphReader) -> None:
        self._gemini_client = gemini_client
        self._graph_reader = graph_reader

    def narrate(self, tag: str, *, top_n: int = _DEFAULT_TOP_N) -> CalibrationNarration:
        """Computes and narrates this household's real variance for
        `tag`.

        Args:
            tag: a real `Outcome.attribution_tags` category value (e.g.
                `"relocation"`) — never invented by this agent; the
                caller (A35 backward framing, or forward-mode branch
                assembly) supplies it.
            top_n: how many `RankedOutcome`s to surface — forwarded
                unchanged to `rank_by_absolute_variance`.

        Returns:
            A `CalibrationNarration`. `model_tier` is `"deterministic"`
            (no Gemini call at all) iff `estimate.sample_size == 0`;
            `"pro"` otherwise. When `estimate.is_thin_history` is `True`,
            `narrative` is guaranteed to contain `estimate.note` verbatim.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or `narrative` was
                blank.
        """
        outcomes = self._graph_reader.outcome_variance(tag)
        estimate = compute_calibration(tag, outcomes)
        ranked_outcomes = rank_by_absolute_variance(outcomes, top_n=top_n)

        if estimate.sample_size == 0:
            return CalibrationNarration(
                tag=tag,
                estimate=estimate,
                ranked_outcomes=ranked_outcomes,
                narrative=estimate.note,
                model_tier="deterministic",
            )

        narrative = self._narrate_with_model(
            tag=tag, ranked_outcomes=ranked_outcomes, estimate_note=estimate.note
        )
        if estimate.is_thin_history:
            narrative = _ensure_note_present(narrative=narrative, note=estimate.note)

        return CalibrationNarration(
            tag=tag, estimate=estimate, ranked_outcomes=ranked_outcomes, narrative=narrative, model_tier="pro"
        )

    def _narrate_with_model(
        self, *, tag: str, ranked_outcomes: tuple[RankedOutcome, ...], estimate_note: str
    ) -> str:
        prompt = load_prompt("A39")
        rendered = prompt.text.format(
            tag=tag,
            estimate_note=estimate_note,
            ranked_outcomes_block=_outcome_lines(tag, ranked_outcomes),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        narrative = require_str(parsed, "narrative", agent_id=AGENT_ID)
        if not narrative.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="narrative must not be blank", raw_text=call_result.text
            )
        return narrative


__all__ = ["AGENT_ID", "CalibrationAgent"]

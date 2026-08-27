"""A33 — Vendor Relations (spec §10.3.F, PHASES.md Phase 7).

*Responsibility:* "Vendor request lifecycle, reliability scoring, switching
proposals." *Model tier:* Flash. *Tools (spec, verbatim):* "communication
(draft), read" — T2 + T0 only. No T3, no T4: this module never sends
anything and, per the split below, never writes the graph from the
*reasoning* half either.

## The spec's own framing, made literal

"The plumber who said 'tomorrow' four days ago" (spec §10.3.F) is a real
latency computation over two real timestamps this module never invents:
when a vendor was asked for something (`requested_at`), and when they
actually did it or said they would (`responded_at`/`promised_at`/
`completed_at`). `VendorRequestObservation` is that raw material — supplied
by the caller (a chat-thread extraction noticing "he said tomorrow," a
future Outbound Concierge call outcome, Phase 10) rather than invented
here; this module has no live channel of its own that observes a vendor
interaction, and does not pretend to.

## Two halves, deliberately split by permission tier

1. **`compute_reliability_score` / `compute_response_latency_hours`** —
   plain deterministic arithmetic over real `VendorRequestObservation`s (no
   model call, same "Flash tier means cheap, not necessarily an LLM call"
   precedent `app.agents.consequence.obligation_writer` and `app.arbitration.
   escalation_agent`'s candidate-selection half both already set).
   `VendorReliabilityUpdater` performs the actual T3 write, wrapping the
   real `GraphWriteTool` — mirrors `app.agents.consequence.
   obligation_writer.ObligationWriter` (A15) being the deterministic writer
   half of a reasoning agent's output.
2. **`VendorRelationsAgent`** — the T2-tier half. Composes a switch-
   proposal *draft* (never sent, never persisted as a graph node by this
   module) when reliability crosses a floor. Model-tier Flash call with a
   deterministic template fallback, following `app.arbitration.
   escalation_agent.EscalationAgent`'s exact established shape for a
   draft/briefing composer.

## A known, honest graph-model gap (raise-worthy, not worked around)

Tracking *individual* vendor-request lifecycle events (request -> response
-> scheduled -> completed) as first-class, later-queryable graph state
would ideally live on `contracts.graph_types.Outcome` nodes (predicted vs.
actual — exactly this shape) linked back to the `VENDOR` they concern. But
`contracts.graph_types.EdgeType`'s frozen table (spec §5.3) has no edge
connecting `OUTCOME` to `VENDOR` at all — `completes_into` is
`OBLIGATION -> OUTCOME` only, and the only edge involving `VENDOR` is
`owed_to` (`LEDGER_EVENT -> VENDOR | PERSON`). Writing a `VENDOR ->
OUTCOME` edge under an existing `EdgeType` would misuse a triple the
repository layer's own validation (`contracts.repositories.GraphWriter`'s
docstring: "responsible for validating that a given (edge_type,
from_node_type, to_node_type) triple is one of the pairs listed in spec
§5.3") was never designed to accept. Rather than force it, this module
persists only the *aggregate* (`Vendor.reliability_score` /
`response_latency_hours`, both already real fields on the frozen `Vendor`
node) and keeps the underlying per-request observations as plain, caller-
supplied data — a real limitation to raise to the CTO for a future ADR
(e.g. a `TRACKS`/`OBSERVED_ON` `VENDOR <-> OUTCOME` edge type), not
something to paper over with a mismatched edge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Derivation, NodeId, Provenance, Vendor

from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient
from app.tools.graph_write_tool import GraphWriteTool

logger = structlog.get_logger(__name__)

_AGENT_ID = AgentId("A33")

_SWITCH_PROPOSAL_RELIABILITY_FLOOR = 0.5
"""Below this `reliability_score`, `VendorRelationsAgent` proposes
considering a switch. A deliberately-documented editorial threshold (like
`app.agents.consequence.obligation_writer`'s title-similarity floors) —
the *inputs* it is computed from are always real observed timestamps,
never invented; only this cutoff is a judgment call."""

_RELIABILITY_CONFIDENCE_SAMPLE_SIZE = 5.0
"""Number of observations at which `VendorReliabilityUpdater` treats its
computed `reliability_score` as fully confident — fewer observations scale
`Provenance.confidence` down linearly, honestly reflecting a smaller
sample rather than claiming full confidence off one data point."""

_ON_TIME_SCORE = 1.0
_LATE_COMPLETION_SCORE = 0.6
_RESPONDED_NEVER_COMPLETED_SCORE = 0.3
_NO_RESPONSE_SCORE = 0.0


@dataclass(frozen=True, slots=True)
class VendorRequestObservation:
    """One real vendor-request lifecycle observation, supplied by the
    caller — see module docstring for why this module has no live source
    of its own. `requested_at` is the only field that is never optional;
    everything after it in the lifecycle (`responded_at` -> `promised_at`
    -> `completed_at`) may genuinely not have happened yet."""

    vendor_id: NodeId
    requested_at: datetime
    responded_at: datetime | None = None
    """When the vendor actually replied (any reply — "yes," "tomorrow,"
    a reschedule) — `None` if they have not responded at all yet."""
    promised_at: datetime | None = None
    """When the vendor said they would do the thing — the "tomorrow" in
    spec's own framing, resolved to a real datetime by whatever upstream
    signal produced this observation (never resolved by this module)."""
    completed_at: datetime | None = None
    """When the work was actually done — `None` if still outstanding."""


def _per_observation_score(observation: VendorRequestObservation) -> float:
    if observation.responded_at is None:
        return _NO_RESPONSE_SCORE
    if observation.completed_at is None:
        return _RESPONDED_NEVER_COMPLETED_SCORE
    if observation.promised_at is not None and observation.completed_at > observation.promised_at:
        return _LATE_COMPLETION_SCORE
    return _ON_TIME_SCORE


def compute_reliability_score(observations: tuple[VendorRequestObservation, ...]) -> float | None:
    """The mean per-observation score across `observations` — `None` (never
    a fabricated default like `0.0` or `1.0`) when there is nothing to
    compute from yet."""
    if not observations:
        return None
    return sum(_per_observation_score(o) for o in observations) / len(observations)


def compute_response_latency_hours(observations: tuple[VendorRequestObservation, ...]) -> float | None:
    """Mean hours from request to first response, across observations that
    *did* get a response. `None` if none of `observations` has responded
    yet — never `0.0` standing in for "no data"."""
    latencies = [
        (o.responded_at - o.requested_at).total_seconds() / 3600.0
        for o in observations
        if o.responded_at is not None
    ]
    if not latencies:
        return None
    return sum(latencies) / len(latencies)


class VendorReliabilityUpdater:
    """The deterministic T3 write half — dependency-injected on the real
    `GraphWriteTool`, so every write here is idempotency-keyed and
    provenance-guarded by the same already-proven machinery `app.adapters.
    financial_signal_ingestion.FinancialSignalIngestor` (A27) reuses,
    never a new write path.
    """

    def __init__(self, *, graph_write_tool: GraphWriteTool) -> None:
        self._graph_write_tool = graph_write_tool

    def update(
        self,
        *,
        vendor: Vendor,
        observations: tuple[VendorRequestObservation, ...],
        as_of: datetime | None = None,
    ) -> Vendor | None:
        """Recomputes `vendor.reliability_score`/`response_latency_hours`
        from `observations` and, if either changed, supersedes `vendor`
        with the updated version.

        Args:
            vendor: the current `Vendor` node (caller-supplied — this
                class holds no `GraphReader`, matching `app.agents.
                consequence.obligation_writer`'s own "caller assembles the
                pool" precedent).
            observations: this vendor's real observed request/response/
                completion history.
            as_of: idempotency-key day-bucket — a fresh scan on the same
                calendar day with the same observation set is a no-op
                replay, not a second write.

        Returns:
            The new `Vendor` version if a write occurred, or `None` if
            `observations` was empty (nothing to compute) or the computed
            values are unchanged from `vendor`'s current ones (no-op,
            no write attempted at all — not even an idempotent one).
        """
        current_time = as_of if as_of is not None else datetime.now(UTC)
        new_score = compute_reliability_score(observations)
        new_latency = compute_response_latency_hours(observations)
        if new_score is None and new_latency is None:
            return None
        if new_score == vendor.reliability_score and new_latency == vendor.response_latency_hours:
            return None

        # AMBIGUOUS, never INFERRED: `Provenance.__post_init__` requires a
        # `source_ref` for INFERRED, and there is genuinely no single
        # source document here — this is an aggregate over `observations`,
        # each of which came from its own (possibly different) source.
        # `confidence` scales with sample size (`_RELIABILITY_CONFIDENCE_
        # SAMPLE_SIZE` observations or more -> full confidence) rather than
        # a flat, invented `1.0` — a score computed from one observation is
        # honestly less trustworthy than one computed from ten.
        updated = replace(
            vendor,
            reliability_score=new_score,
            response_latency_hours=new_latency,
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=min(1.0, len(observations) / _RELIABILITY_CONFIDENCE_SAMPLE_SIZE),
                deriving_agent=_AGENT_ID,
                created_at=current_time,
            ),
        )
        idempotency_key = f"vendor_reliability_update:{vendor.id}:{current_time.date().isoformat()}"
        self._graph_write_tool.invoke_idempotent(idempotency_key, operation="write_node", node=updated)
        logger.info(
            "adapters.vendor_relations.a33.reliability_updated",
            vendor_id=str(vendor.id),
            reliability_score=new_score,
            response_latency_hours=new_latency,
            observation_count=len(observations),
        )
        return updated


@dataclass(frozen=True, slots=True)
class VendorSwitchProposalDraft:
    """A T2-tier draft only — never sent, never persisted as a graph node
    by this module (see module docstring's graph-model-gap note)."""

    vendor_id: NodeId
    reliability_score: float
    draft_text: str
    is_template_fallback: bool


_SWITCH_PROPOSAL_PROMPT = """You are the Vendor Relations assistant for a household operating system. \
Compose a short, clear note (2-3 sentences) for a household member, proposing they consider switching \
away from a vendor whose reliability has been poor, based only on the real observed data below. Do not \
invent specific incidents beyond what is given. Do not choose a replacement vendor yourself — that is the \
household's decision.

Vendor category: {category}
Observed reliability score (0.0-1.0, higher is better): {reliability_score:.2f}
Observed average response latency (hours), if any: {latency_text}
Number of requests this score is based on: {observation_count}

Respond with the note text only — no JSON, no markdown, no preamble."""


def _template_switch_proposal(vendor: Vendor, reliability_score: float, observation_count: int) -> str:
    return (
        f"This {vendor.category} vendor's observed reliability score is {reliability_score:.2f} "
        f"(based on {observation_count} tracked request(s)) — below the household's usual bar. "
        "Automated briefing unavailable; consider reviewing the vendor's recent request history "
        "and whether an alternative provider is worth exploring."
    )


class VendorRelationsAgent:
    """A33's T2-tier half — dependency-injected on a `GeminiClient`,
    mirroring `app.arbitration.escalation_agent.EscalationAgent`'s exact
    established shape for a draft/briefing composer with a deterministic
    fallback."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def propose_switch_if_warranted(
        self, *, vendor: Vendor, observations: tuple[VendorRequestObservation, ...]
    ) -> VendorSwitchProposalDraft | None:
        """Returns a switch-proposal draft only when the real, observed
        `reliability_score` falls below `_SWITCH_PROPOSAL_RELIABILITY_FLOOR`
        — `None` (no draft at all, not an empty one) when there is not
        enough observed data yet or reliability is acceptable.
        """
        reliability_score = compute_reliability_score(observations)
        if reliability_score is None or reliability_score >= _SWITCH_PROPOSAL_RELIABILITY_FLOOR:
            return None

        latency = compute_response_latency_hours(observations)
        latency_text = f"{latency:.1f}" if latency is not None else "no responses recorded yet"
        prompt = _SWITCH_PROPOSAL_PROMPT.format(
            category=vendor.category,
            reliability_score=reliability_score,
            latency_text=latency_text,
            observation_count=len(observations),
        )
        try:
            call_result = self._gemini_client.generate_text(
                agent_id=_AGENT_ID, tier=ModelTier.FLASH, prompt=prompt
            )
        except GeminiCallFailed as exc:
            logger.warning(
                "adapters.vendor_relations.a33.draft_call_failed", vendor_id=str(vendor.id), reason=str(exc)
            )
            return VendorSwitchProposalDraft(
                vendor_id=vendor.id,
                reliability_score=reliability_score,
                draft_text=_template_switch_proposal(vendor, reliability_score, len(observations)),
                is_template_fallback=True,
            )

        return VendorSwitchProposalDraft(
            vendor_id=vendor.id,
            reliability_score=reliability_score,
            draft_text=call_result.text.strip(),
            is_template_fallback=False,
        )


__all__ = [
    "VendorReliabilityUpdater",
    "VendorRelationsAgent",
    "VendorRequestObservation",
    "VendorSwitchProposalDraft",
    "compute_reliability_score",
    "compute_response_latency_hours",
]

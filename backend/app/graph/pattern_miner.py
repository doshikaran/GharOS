"""A10 — Pattern Miner (spec §15.2, §20; PHASES.md Phase 14; ADR-021
Decision 1).

Scheduled, **Pro-tier** (spec: "mining regularities into a durable claim
is judgment, not extraction"). Mines `Outcome` history for genuine
regularities — spec's own worked example: "appointments scheduled Monday
slip 60% of the time," a systematic correlation between a categorical
feature of an `Outcome`'s context and its variance, not a one-off.

**Deterministic gate, judgment narration — mirrors A39 Calibration's own
split (`app.solvers.calibration_stats` / `app.agents.simulator.
calibration_agent`) exactly:** *whether* a candidate regularity clears the
bar for a durable `Pattern` claim is decided entirely by
`_find_candidate` below — plain arithmetic over real `Outcome.variance`
values, zero model involvement, zero chance of an LLM talking its way
past the threshold. The **Pro-tier Gemini call only phrases the
already-decided candidate's `description`** in the household-specific,
plain-English style spec's own example uses — it never decides whether a
`Pattern` gets written, and its output cannot lower `support_count` or
invent a slip rate the arithmetic didn't produce (`_render_description`'s
prompt echoes the exact numbers computed in code; a template fallback is
used if the model response is unusable, never a blank/omitted
description).

## The categorical feature this module mines over: `Outcome.attribution_tags`

`GraphReader` (the frozen Protocol) offers no "list every `Outcome`" or
"list every attribution tag in use" operation — by design, `history`/
`outcome_variance` are both keyed queries, not full scans (ADR-021: zero
new `contracts/` surface this phase). Mining is therefore driven by a
**documented, extensible candidate tag vocabulary**
(`CANDIDATE_ATTRIBUTION_TAGS` below), each queried via the existing
`GraphReader.outcome_variance(tag)` — exactly the reuse ADR-021 directs
("Reads `GraphReader.history`/`.outcome_variance` ... already read OUTCOME
records"). This candidate list is the union of every `Outcome.
attribution_tags` convention this codebase has established so far:

- ADR-016 (Phase 10) provider-reliability tags: `no_show`, `on_time`,
  `rescheduled`, `unresponsive_to_automated_caller`.
- ADR-017 (Phase 11) decision-category tags: `relocation`,
  `school_transition`, `staff_transition`, `major_purchase`.
- **New, fourth convention, established here (Phase 14):**
  `scheduled_<weekday>` (lowercase full English weekday name — e.g.
  `scheduled_monday`), applied by whichever agent creates an `Outcome`
  from a completed `Obligation`, recording the weekday its originating
  `due_at`/`must_start_by` fell on. Established because spec's own
  canonical worked example ("appointments scheduled Monday slip 60% of
  the time") needs a day-of-week categorical feature that no existing
  tag convention captures — consistent with ADR-015/016/017's shared
  pattern of layering a new, self-documented value vocabulary onto this
  one free-text field rather than adding a new node/edge type for it.

A tag with zero seeded/real `Outcome`s is simply never a candidate this
run (`outcome_variance` returns `()`, `_find_candidate` returns `None`
below threshold) — never an error, mirroring `calibration_stats`'s own
"thin/zero history is honest, not fabricated" posture.

## The "slipped" signal: variance sign

This graph's existing seeded `Outcome`s already establish a consistent
sign convention across both time- and cost-denominated variances:
positive `variance` means "worse than predicted" (a school admission 14
days *late*; a purchase INR 1,500 *over* budget), negative means "better
than predicted" (staff onboarding 14 days *ahead* of the expected
adjustment period). `_find_candidate` reuses that existing convention
rather than inventing a second one: `variance > 0` counts as "slipped."

**Forbidden, hard gate in code — not a prompt instruction:** a candidate
whose resolved-variance sample size is below `MIN_PATTERN_SUPPORT`, or
whose slip rate is below `MIN_PATTERN_SLIP_RATE`, is dropped inside
`_find_candidate` and never constructed as a `Pattern` object, let alone
passed to `PatternRepository.write_pattern` — proven by
`test_pattern_miner.py::TestSupportThresholdGate`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import (
    AgentId,
    Derivation,
    NodeId,
    Outcome,
    Pattern,
    Provenance,
)
from contracts.repositories import GraphReader, PatternRepository

from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient

logger = structlog.get_logger(__name__)

AGENT_ID = AgentId("A10")

MIN_PATTERN_SUPPORT: int = 3
"""Same naming/threshold convention as Phase 11's `calibration_stats.
MIN_SAMPLE_SIZE_FOR_CALIBRATION` (also `3`): below this many real,
resolved-variance `Outcome`s for a tag, a claimed regularity is a
one-off or a guess, not a mined pattern — spec's own forbidden-list line
for A10 ("creating patterns below a support threshold")."""

MIN_PATTERN_SLIP_RATE: float = 0.5
"""The fraction of a tag's resolved-variance `Outcome`s that must show
`variance > 0` ("slipped," see module docstring) before the correlation
is a real regularity worth a durable claim, rather than noise a small
sample produced by chance. `0.5` = "more likely than not" — clears
spec's own worked example (60%) with room to spare, and is the lowest
bar that still means the tagged condition is *associated* with slipping
more often than not, not merely present in a slip that happened anyway.
Independent of, and checked in addition to, `MIN_PATTERN_SUPPORT` — both
must clear for a `Pattern` to be written."""

CANDIDATE_ATTRIBUTION_TAGS: tuple[str, ...] = (
    # ADR-016 (Phase 10) — provider-reliability convention.
    "no_show",
    "on_time",
    "rescheduled",
    "unresponsive_to_automated_caller",
    # ADR-017 (Phase 11) — decision-category convention.
    "relocation",
    "school_transition",
    "staff_transition",
    "major_purchase",
    # This module (Phase 14) — scheduled-weekday convention (see module
    # docstring).
    "scheduled_monday",
    "scheduled_tuesday",
    "scheduled_wednesday",
    "scheduled_thursday",
    "scheduled_friday",
    "scheduled_saturday",
    "scheduled_sunday",
)
"""Extensible by construction: a later phase establishing a fifth
`attribution_tags` convention adds its values here, never changes the
mining logic itself (`_find_candidate` is generic over any tag string)."""

_FALLBACK_DESCRIPTION_TEMPLATE = (
    "Regularity detected: outcomes tagged {tag!r} ran worse than predicted "
    "in {slipped}/{sample_size} sampled cases ({slip_rate:.0%})."
)


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    """A regularity that has already cleared both deterministic
    thresholds — everything `_render_description` and `run` need, with
    nothing left for either to (re)compute."""

    tag: str
    sample_size: int
    slipped_count: int
    slip_rate: float
    contributing_outcome_ids: tuple[NodeId, ...]


def _find_candidate(tag: str, outcomes: tuple[Outcome, ...]) -> PatternCandidate | None:
    """The hard, deterministic gate. Returns `None` — never a low-
    confidence `Pattern`, never a partially-built one — for any tag that
    does not clear both `MIN_PATTERN_SUPPORT` and `MIN_PATTERN_SLIP_RATE`.

    Args:
        tag: the `Outcome.attribution_tags` value being evaluated.
        outcomes: `GraphReader.outcome_variance(tag)`'s result for `tag`.

    Returns:
        A `PatternCandidate` if `tag` is a real regularity by this
        module's own thresholds, else `None`.
    """
    resolved = tuple(outcome for outcome in outcomes if outcome.variance is not None)
    sample_size = len(resolved)
    if sample_size < MIN_PATTERN_SUPPORT:
        return None
    slipped = tuple(outcome for outcome in resolved if outcome.variance is not None and outcome.variance > 0)
    slip_rate = len(slipped) / sample_size
    if slip_rate < MIN_PATTERN_SLIP_RATE:
        return None
    return PatternCandidate(
        tag=tag,
        sample_size=sample_size,
        slipped_count=len(slipped),
        slip_rate=slip_rate,
        contributing_outcome_ids=tuple(outcome.id for outcome in resolved),
    )


class PatternMiner:
    """A10 Pattern Miner. Dependency-injected on a `GraphReader`, a
    `PatternRepository`, and a `GeminiClient` — no `GraphWriter` import
    (this agent writes only `Pattern` nodes, through the narrower,
    purpose-built `PatternRepository`, per `contracts.repositories.
    PatternRepository`'s own docstring: "Written only by the Pattern
    Miner (A10)")."""

    def __init__(
        self,
        *,
        graph_reader: GraphReader,
        pattern_repository: PatternRepository,
        gemini_client: GeminiClient,
    ) -> None:
        self._graph_reader = graph_reader
        self._pattern_repository = pattern_repository
        self._gemini_client = gemini_client

    def run(self, *, now: datetime | None = None) -> tuple[Pattern, ...]:
        """One full A10 mining pass over `CANDIDATE_ATTRIBUTION_TAGS`.

        For each candidate tag that clears `_find_candidate`'s
        deterministic gate, writes exactly one `Pattern` via
        `PatternRepository.write_pattern`. A tag whose Pro-tier
        description call fails (`GeminiCallFailed`) is logged and
        skipped for this run rather than aborting the remaining
        candidates — one bad model call must not silently drop every
        other real regularity this run would otherwise have found (and
        never fabricates a description in its place; see
        `_render_description`'s own honest template fallback for the
        distinct, narrower case of a *malformed but received* response).

        Returns:
            Every `Pattern` actually written this run, in candidate-tag
            order.
        """
        reference_time = now if now is not None else datetime.now(UTC)
        written: list[Pattern] = []
        for tag in CANDIDATE_ATTRIBUTION_TAGS:
            outcomes = self._graph_reader.outcome_variance(tag)
            candidate = _find_candidate(tag, outcomes)
            if candidate is None:
                continue
            try:
                pattern = self._build_pattern(candidate, now=reference_time)
            except GeminiCallFailed as exc:
                logger.warning(
                    "pattern_miner.description_call_failed_skipping_tag",
                    tag=tag,
                    reason=exc.reason,
                )
                continue
            self._pattern_repository.write_pattern(pattern)
            written.append(pattern)
            logger.info(
                "pattern_miner.pattern_written",
                tag=tag,
                pattern_id=str(pattern.id),
                support_count=pattern.support_count,
                slip_rate=candidate.slip_rate,
            )
        return tuple(written)

    def _build_pattern(self, candidate: PatternCandidate, *, now: datetime) -> Pattern:
        description = self._render_description(candidate)
        return Pattern(
            id=NodeId(f"pattern-mined-{candidate.tag}-{uuid.uuid4().hex[:12]}"),
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=candidate.slip_rate,
                deriving_agent=AGENT_ID,
                created_at=now,
            ),
            description=description,
            support_count=candidate.sample_size,
            contributing_outcome_ids=candidate.contributing_outcome_ids,
        )

    def _render_description(self, candidate: PatternCandidate) -> str:
        """The Pro-tier narration step — phrasing only, never the
        decision (see module docstring). Falls back to a deterministic
        template (never a blank description) if the model response is
        empty or unusable, so a malformed narration never blocks a
        candidate that already, correctly, cleared the deterministic
        gate."""
        prompt = (
            "You are narrating one already-confirmed household regularity for a "
            "family operating system. Do not add numbers, hedge, or change the "
            "facts below — restate them in one clear, plain-English sentence in "
            'the style of this example: "Appointments scheduled on Monday slip '
            'in this household 60% of the time."\n\n'
            f"Tag: {candidate.tag}\n"
            f"Sample size (real past outcomes): {candidate.sample_size}\n"
            f"Number that slipped (worse than predicted): {candidate.slipped_count}\n"
            f"Slip rate: {candidate.slip_rate:.0%}\n\n"
            "Respond with the one sentence only, no preamble, no quotation marks."
        )
        result = self._gemini_client.generate_text(agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=prompt)
        # `GeminiClient.generate_text` already raises `GeminiCallFailed`
        # itself for a *falsy* response (empty string / no text content) —
        # this method never sees that case. What it still must guard
        # against is a purely-whitespace response: truthy in Python
        # (`bool("   ")` is `True`, so `GeminiClient`'s own emptiness check
        # does not catch it) but empty once normalised, which would
        # otherwise silently write a blank `Pattern.description`.
        text = result.text.strip()
        if not text:
            return _FALLBACK_DESCRIPTION_TEMPLATE.format(
                tag=candidate.tag,
                slipped=candidate.slipped_count,
                sample_size=candidate.sample_size,
                slip_rate=candidate.slip_rate,
            )
        return text


__all__ = [
    "AGENT_ID",
    "CANDIDATE_ATTRIBUTION_TAGS",
    "MIN_PATTERN_SLIP_RATE",
    "MIN_PATTERN_SUPPORT",
    "PatternCandidate",
    "PatternMiner",
]

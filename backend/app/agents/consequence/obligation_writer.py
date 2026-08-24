"""A15 — Obligation Writer (spec §7.3 Stage 4, §15.4).

*Responsibility:* persist A12's citation-validated, confidence-cleared
implied candidates as real OBLIGATION nodes with full provenance —
deduping cross-channel repeats, superseding genuine follow-ups, and
computing `must_start_by`.

*Model tier:* Flash/deterministic per the roster — **this module makes no
LLM call at all.** Every decision here (is this a duplicate, is this a
genuine update, what is the write order, what is `must_start_by`) is
plain deterministic code over already-validated candidate data; there is
nothing left here that needs a model's judgment. `contracts.graph_types.
AgentId("A15")` never appears as an argument to
`reasoning.gemini_client.GeminiClient` anywhere in this file.

*Forbidden:* **modifying content.** This module never changes a
candidate's `title`, `obligation_type`, `due_at`, or `effort_estimate_
minutes` — the only field it computes itself is `must_start_by` (a
genuinely new, structurally-required field A12 never populates), and the
only content-shaped decision it makes is *which existing node* (if any) a
candidate corresponds to, never a rewrite of what the candidate says.

## Dedupe vs. supersede — the actual decision rule

A candidate whose `obligation_type` matches an existing open/stated
obligation and whose title shares enough vocabulary
(`_DUPLICATE_TITLE_SIMILARITY_FLOOR`) is treated as referring to the
*same* underlying commitment. From there:

- **Pure duplicate → dedupe, no new write.** Title near-identical
  (`_NEAR_IDENTICAL_TITLE_SIMILARITY`), `due_at` within
  `_SAME_DUE_AT_TOLERANCE`, and the same effort estimate — this is the
  same fact arriving twice (e.g. WhatsApp and email both mentioning the
  same field trip fee), not new information. The existing node's id is
  returned; nothing is written.
- **Meaningfully changed → supersede.** Same underlying commitment but a
  real change (a moved due date beyond tolerance, a different effort
  estimate, or title vocabulary similar-but-not-identical) — a genuine
  follow-up, written as a new version via `GraphWriter.supersede_node`
  plus an explicit `supersedes` edge, never silently overwritten in
  place (gharos-standards: writes create versions).
- **No match at all → new obligation**, written fresh.

## `must_start_by` — real, but honestly scoped (DEBT-006)

Computed from `GraphReader.dependency_chain()` (ADR-011) plus `due_at`
alone: the earliest `due_at` anywhere in the obligation's own forward
dependency chain (itself plus every prerequisite it transitively
`depends_on`), minus its own `effort_estimate_minutes`. This is a real,
defensible backward computation using exactly the two data sources
DEBT-006 documents as actually available on the frozen contract today —
**it is explicitly NOT availability-aware** (`contracts.graph_types.
Person` has no `availability` field to consult; see DEBT-006). The spec
§7.3 worked example's "must be signed Monday because the usual signer
travels Tue-Wed" reasoning needs availability data this contract does not
yet expose — this module computes the honest, due-date-and-dependency-
only lower bound instead of inventing an availability heuristic to fake
that specific number.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Provenance,
    SourceRef,
)
from contracts.repositories import GraphReader, GraphWriter

from .errors import CandidateDependencyCycle
from .types import HouseholdContext, ImpliedObligationCandidate, WriteOutcome

AGENT_ID = AgentId("A15")

_CONTENT_DERIVING_AGENT = AgentId("A12")
"""`Provenance.deriving_agent` for every OBLIGATION node and `implies`/
`depends_on` edge this module writes — the *content* (title, due date,
reasoning) was A12's inference, not A15's; A15 is the mechanical writer,
matching the established convention `app.agents.intake.strategies.
_common.provenance_for` sets (a strategy's `map_to_graph` writes nodes
whose content came from A3's extraction, attributed to A3, not to the
strategy). The one exception is the `supersedes` edge itself — *that*
relationship (this candidate replaces that existing node) is A15's own
dedup/supersession judgment, so it is attributed to `AGENT_ID` (A15)."""

logger = structlog.get_logger(__name__)

_CLOSED_OBLIGATION_STATUSES = (
    ObligationStatus.COMPLETED,
    ObligationStatus.DROPPED,
    ObligationStatus.SUPERSEDED,
)

_TITLE_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
_DUPLICATE_TITLE_SIMILARITY_FLOOR = 0.6
"""Minimum title-token Jaccard similarity for a candidate to be considered
possibly-the-same-commitment as an existing obligation at all. Below this,
the two are treated as genuinely unrelated (a new, distinct obligation)."""
_NEAR_IDENTICAL_TITLE_SIMILARITY = 0.9
"""At or above this (combined with a close `due_at` and identical effort
estimate), two titles are the same fact restated, not an update."""
_SAME_DUE_AT_TOLERANCE = timedelta(hours=1)
"""`due_at` values within this tolerance of each other are "the same
time" for duplicate-detection purposes — real cross-channel restatements
of the same event are rarely byte-identical timestamps (a WhatsApp
message rounds to "1:30", an email says "13:30:00")."""


def _title_tokens(text: str) -> set[str]:
    return set(_TITLE_TOKEN_PATTERN.findall(text.lower()))


def _title_similarity(title_a: str, title_b: str) -> float:
    tokens_a, tokens_b = _title_tokens(title_a), _title_tokens(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _find_possible_match(
    candidate: ImpliedObligationCandidate, pool: tuple[Obligation, ...]
) -> Obligation | None:
    """Best `obligation_type`-matching, sufficiently-title-similar open
    obligation in `pool`, or `None` if nothing clears the floor. Closed-
    status obligations are never matched against — a completed/dropped/
    superseded obligation is not "the same open commitment" to dedupe or
    supersede."""
    best: Obligation | None = None
    best_score = 0.0
    for existing in pool:
        if existing.status in _CLOSED_OBLIGATION_STATUSES:
            continue
        if existing.obligation_type != candidate.obligation_type:
            continue
        score = _title_similarity(candidate.title, existing.title)
        if score >= _DUPLICATE_TITLE_SIMILARITY_FLOOR and score > best_score:
            best = existing
            best_score = score
    return best


def _is_pure_duplicate(candidate: ImpliedObligationCandidate, existing: Obligation) -> bool:
    """`True` when `candidate` is the same fact restated, not an update —
    see this module's docstring for the full rule."""
    if candidate.due_at is None and existing.due_at is None:
        due_close = True
    elif candidate.due_at is not None and existing.due_at is not None:
        due_close = abs(candidate.due_at - existing.due_at) <= _SAME_DUE_AT_TOLERANCE
    else:
        due_close = False
    effort_close = (candidate.effort_estimate_minutes or 0) == (existing.effort_estimate_minutes or 0)
    title_similarity = _title_similarity(candidate.title, existing.title)
    title_near_identical = title_similarity >= _NEAR_IDENTICAL_TITLE_SIMILARITY
    return due_close and effort_close and title_near_identical


def _topological_order(
    candidates: tuple[ImpliedObligationCandidate, ...],
) -> tuple[ImpliedObligationCandidate, ...]:
    """Orders `candidates` so every candidate is written only after every
    other candidate *in this same batch* that it `depends_on` — required
    so a later `GraphReader.dependency_chain()` call can resolve real,
    already-written prerequisite nodes. A `depends_on_candidate_ids` entry
    that does not refer to another candidate in this batch is not a
    same-batch ordering constraint (it is resolved, or logged and
    dropped, at actual edge-write time in `ObligationWriter.write`).

    Raises:
        errors.CandidateDependencyCycle: `candidates`' same-batch
            dependencies form a cycle — no valid write order exists.
    """
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    order_index = {candidate.candidate_id: index for index, candidate in enumerate(candidates)}
    in_degree = {candidate.candidate_id: 0 for candidate in candidates}
    dependents: dict[str, list[str]] = {candidate.candidate_id: [] for candidate in candidates}

    for candidate in candidates:
        for dep_id in candidate.depends_on_candidate_ids:
            if dep_id not in by_id:
                continue
            in_degree[candidate.candidate_id] += 1
            dependents[dep_id].append(candidate.candidate_id)

    queue: deque[str] = deque(
        sorted((cid for cid, degree in in_degree.items() if degree == 0), key=lambda cid: order_index[cid])
    )
    ordered_ids: list[str] = []
    while queue:
        current_id = queue.popleft()
        ordered_ids.append(current_id)
        for dependent_id in sorted(dependents[current_id], key=lambda cid: order_index[cid]):
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                queue.append(dependent_id)

    if len(ordered_ids) != len(candidates):
        remaining = tuple(cid for cid in by_id if cid not in ordered_ids)
        raise CandidateDependencyCycle(candidate_ids_in_cycle=remaining)

    return tuple(by_id[cid] for cid in ordered_ids)


def _compute_must_start_by(obligation: Obligation, chain: tuple[Obligation, ...]) -> datetime | None:
    """See this module's docstring for the full rationale (DEBT-006):
    the earliest `due_at` across `obligation` and its full forward
    dependency chain, minus `obligation`'s own effort estimate. `None`
    when no `due_at` exists anywhere in the chain — never a fabricated
    default."""
    due_candidates = [node.due_at for node in (obligation, *chain) if node.due_at is not None]
    if not due_candidates:
        return None
    earliest_due = min(due_candidates)
    buffer_minutes = obligation.effort_estimate_minutes or 0
    return earliest_due - timedelta(minutes=buffer_minutes)


def _new_provenance(*, source_document_id: NodeId, candidate: ImpliedObligationCandidate) -> Provenance:
    return Provenance(
        derivation=Derivation.INFERRED,
        source_ref=SourceRef(source_document_id=source_document_id, region=candidate.citation.region),
        confidence=candidate.confidence,
        deriving_agent=_CONTENT_DERIVING_AGENT,
        created_at=datetime.now(UTC),
    )


class ObligationWriter:
    """A15 Obligation Writer. Dependency-injected on a `GraphReader` and a
    `GraphWriter` — the only Consequence Engine agent with write access to
    the graph (A12/A13/A14/A16 all read-only or no graph access at all)."""

    def __init__(self, *, graph_reader: GraphReader, graph_writer: GraphWriter) -> None:
        self._reader = graph_reader
        self._writer = graph_writer

    def write(
        self,
        *,
        source_document_id: NodeId,
        candidates: tuple[ImpliedObligationCandidate, ...],
        household_context: HouseholdContext,
    ) -> tuple[WriteOutcome, ...]:
        """Persists `candidates`, deduping/superseding against
        `household_context`'s existing obligations, then computes
        `must_start_by` for everything newly written.

        Args:
            source_document_id: the SOURCE_DOCUMENT `implies` edges point
                back to.
            candidates: A12's candidates for this document — already
                citation-validated and confidence-cleared; this module
                trusts that and performs no re-validation of its own.
            household_context: existing household state to dedupe/
                supersede against (`open_obligations` + `stated_obligations`).

        Returns:
            One `WriteOutcome` per candidate, in the same order given.

        Raises:
            errors.CandidateDependencyCycle: `candidates`' same-batch
                dependencies form a cycle.
            contracts.errors.ProvenanceMissing: should be structurally
                unreachable (every write here builds complete provenance)
                — propagates unchanged if it ever somehow fires.
        """
        if not candidates:
            return ()

        ordered = _topological_order(candidates)
        existing_pool: list[Obligation] = list(
            household_context.open_obligations + household_context.stated_obligations
        )
        candidate_id_to_node_id: dict[str, NodeId] = {}
        newly_written_node_ids: list[NodeId] = []
        outcome_by_candidate_id: dict[str, WriteOutcome] = {}

        for candidate in ordered:
            match = _find_possible_match(candidate, tuple(existing_pool))

            if match is not None and _is_pure_duplicate(candidate, match):
                candidate_id_to_node_id[candidate.candidate_id] = match.id
                outcome_by_candidate_id[candidate.candidate_id] = WriteOutcome(
                    candidate_id=candidate.candidate_id,
                    node_id=match.id,
                    action="deduplicated",
                    detail=(
                        f"matches existing obligation {match.id} ({match.title!r}) — "
                        "same fact, not written again"
                    ),
                )
                logger.info(
                    "agents.consequence.a15.deduplicated",
                    candidate_id=candidate.candidate_id,
                    matched_node_id=str(match.id),
                )
                continue

            new_obligation = Obligation(
                id=NodeId(f"obligation:{uuid.uuid4().hex}"),
                provenance=_new_provenance(source_document_id=source_document_id, candidate=candidate),
                title=candidate.title,
                obligation_type=candidate.obligation_type,
                due_at=candidate.due_at,
                must_start_by=None,
                effort_estimate_minutes=candidate.effort_estimate_minutes,
                status=ObligationStatus.DERIVED,
                stated_or_implied=ObligationDerivation.IMPLIED,
            )

            if match is not None:
                written_id = self._writer.supersede_node(match.id, new_obligation)
                self._writer.write_edge(
                    Edge(
                        id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                        provenance=Provenance(
                            derivation=Derivation.INFERRED,
                            source_ref=SourceRef(
                                source_document_id=source_document_id, region=candidate.citation.region
                            ),
                            confidence=candidate.confidence,
                            deriving_agent=AGENT_ID,
                            created_at=datetime.now(UTC),
                        ),
                        edge_type=EdgeType.SUPERSEDES,
                        from_id=written_id,
                        to_id=match.id,
                    )
                )
                action: Literal["written", "deduplicated", "superseded", "rejected"] = "superseded"
                detail = f"supersedes existing obligation {match.id} ({match.title!r}) — genuine follow-up"
                logger.info(
                    "agents.consequence.a15.superseded",
                    candidate_id=candidate.candidate_id,
                    old_node_id=str(match.id),
                    new_node_id=str(written_id),
                )
            else:
                written_id = self._writer.write_node(new_obligation)
                action = "written"
                detail = "new implied obligation"
                logger.info(
                    "agents.consequence.a15.written",
                    candidate_id=candidate.candidate_id,
                    node_id=str(written_id),
                )

            self._writer.write_edge(
                Edge(
                    id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                    provenance=_new_provenance(source_document_id=source_document_id, candidate=candidate),
                    edge_type=EdgeType.IMPLIES,
                    from_id=source_document_id,
                    to_id=written_id,
                )
            )

            for dep_candidate_id in candidate.depends_on_candidate_ids:
                dep_node_id = candidate_id_to_node_id.get(dep_candidate_id)
                if dep_node_id is None:
                    logger.warning(
                        "agents.consequence.a15.dropped_dependency_reference",
                        candidate_id=candidate.candidate_id,
                        dep_candidate_id=dep_candidate_id,
                    )
                    continue
                self._writer.write_edge(
                    Edge(
                        id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                        provenance=_new_provenance(
                            source_document_id=source_document_id, candidate=candidate
                        ),
                        edge_type=EdgeType.DEPENDS_ON,
                        from_id=written_id,
                        to_id=dep_node_id,
                    )
                )

            candidate_id_to_node_id[candidate.candidate_id] = written_id
            existing_pool.append(new_obligation)
            newly_written_node_ids.append(written_id)
            outcome_by_candidate_id[candidate.candidate_id] = WriteOutcome(
                candidate_id=candidate.candidate_id, node_id=written_id, action=action, detail=detail
            )

        self._backfill_must_start_by(newly_written_node_ids)

        return tuple(outcome_by_candidate_id[candidate.candidate_id] for candidate in candidates)

    def _backfill_must_start_by(self, node_ids: list[NodeId]) -> None:
        """Second pass: now that every candidate in the batch (and its
        `depends_on` edges) is durably written, compute and persist
        `must_start_by` for each freshly-written node — this genuinely
        needs `GraphReader.dependency_chain()` to resolve real graph
        state, which only exists after the first pass's writes land."""
        for node_id in node_ids:
            current = self._reader.get_node(node_id)
            if not isinstance(current, Obligation):
                continue  # pragma: no cover — defensive; we just wrote this as an Obligation
            chain = self._reader.dependency_chain(node_id)
            must_start_by = _compute_must_start_by(current, chain)
            if must_start_by is None:
                continue
            self._writer.write_node(replace(current, must_start_by=must_start_by))


__all__ = ["AGENT_ID", "ObligationWriter"]

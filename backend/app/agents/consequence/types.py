"""Shared, non-agent-specific dataclasses for the Consequence Engine
(A12-A16, spec §7). Not itself an agent — these are the shapes that flow
between A12 -> A13 -> A14 -> A15 (and A16, reasoning over the same
candidate/document stream independently).

Kept separate from any one agent module so `implication_agent.py`,
`constraint_checker.py`, `conflict_radar.py`, `obligation_writer.py`, and
`constraint_learner.py` all import the same candidate/finding shapes
rather than each defining a slightly different one (the kind of drift that
makes a 5-agent pipeline hard to reason about end to end).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from contracts.agents import Citation
from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId, Obligation, Person

# ---------------------------------------------------------------------------
# Household context — the read side of "read via GraphReader" (see
# `context.py` for how this is assembled from a real graph).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HouseholdContext:
    """Pre-resolved household state A12/A13/A14/A16 reason against.

    Assembled by the caller via `contracts.repositories.GraphReader`
    (`context.gather_household_context` does this for a real graph) rather
    than each agent performing its own unrestricted graph enumeration:
    `contracts.repositories.GraphReader` (frozen, CTO-owned) has no
    "list every node of type X in the household" primitive — every one of
    its 14 query operations (spec §5.7) is scoped by a specific
    node/edge/window, not an open scan. Modeling this as a plain resolved
    data bundle keeps every reasoning agent's core logic decoupled from
    Firestore/graph-reader mechanics (hexagonal architecture,
    gharos-standards skill) and trivially unit-testable without a graph at
    all.
    """

    people: tuple[Person, ...]
    constraints: tuple[Constraint, ...]
    open_obligations: tuple[Obligation, ...]
    stated_obligations: tuple[Obligation, ...]
    """OBLIGATIONs already linked to the SOURCE_DOCUMENT under
    consideration via a `states` edge (Phase 3's output) — what A12 must
    NOT re-derive; only what goes beyond this is a genuine implication."""


# ---------------------------------------------------------------------------
# A12 — Implication Agent output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImpliedObligationCandidate:
    """One implied obligation A12 proposes — not yet written to the graph
    (A15's job). Every instance that exists has already passed
    citation-resolvability validation (`citation_validator.py`) — an
    uncitable candidate is discarded before this type is ever constructed
    (spec §7.6: "uncitable -> discarded", the single most safety-critical
    rule in this phase; see `implication_agent.py`)."""

    candidate_id: str
    title: str
    obligation_type: str
    due_at: datetime | None
    effort_estimate_minutes: int | None
    reasoning: str
    citation: Citation
    cited_span_text: str
    """The literal text the code resolved at `citation`'s region — kept on
    the candidate (not just the citation) so downstream code/tests/CTO
    review can inspect exactly what was verified without re-resolving."""
    confidence: float
    depends_on_candidate_ids: tuple[str, ...] = ()
    """Other candidate ids (from the same `ImplicationRunResult`) this one
    cannot start before — feeds A15's must-start-by computation (spec §7.3
    Stage 4: "working backwards through dependencies and availability")."""


@dataclass(frozen=True, slots=True)
class DiscardedInference:
    """One candidate A12's model proposed but that never became an
    `ImpliedObligationCandidate` — logged for audit, never surfaced to a
    caller "at low confidence" (spec §7.6). `discard_reason` always names
    a specific, checkable failure, never a generic "rejected"."""

    title: str
    reasoning: str
    claimed_region: str | None
    claimed_span_text: str | None
    discard_reason: str


@dataclass(frozen=True, slots=True)
class ImplicationRequest:
    """A12's input: one SOURCE_DOCUMENT's literal text plus the household
    context to reason against. `document_text` is the actual decoded
    document content (not a summary) — A12 cites byte-offset spans into
    its UTF-8 encoding, so this must be exactly the text the citations
    were computed against."""

    source_document_id: NodeId
    document_text: str
    household_context: HouseholdContext


@dataclass(frozen=True, slots=True)
class ImplicationRunResult:
    candidates: tuple[ImpliedObligationCandidate, ...]
    discarded: tuple[DiscardedInference, ...]
    model_tier: Literal["flash", "pro", "deterministic"]
    prompt_version: str
    confidence: float
    invocation_id: str


# ---------------------------------------------------------------------------
# A13 — Constraint Checker output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConstraintCheckFinding:
    """A13's verdict on one candidate against one existing CONSTRAINT.
    Never carries a proposed fix — A13 is forbidden from resolving
    violations (spec §15.4 A13); it only reports."""

    candidate_id: str
    constraint_id: NodeId
    constraint_kind: ConstraintKind
    severity: ConstraintSeverity
    violates: bool
    explanation: str
    confidence: float
    escalated_to_pro: bool


# ---------------------------------------------------------------------------
# A14 — Conflict Radar output shapes
# ---------------------------------------------------------------------------

ConflictKind = Literal["temporal", "resource", "capability", "load"]


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    """One detected collision — between two candidates, or a candidate and
    existing graph state. A14 never resolves a multi-person conflict; this
    finding is the entirety of its output for that collision (spec §15.4
    A14 forbidden list)."""

    kind: ConflictKind
    subject_candidate_id: str
    other_id: str
    """Either another candidate's `candidate_id`, or a `NodeId` (as `str`)
    of an existing colliding OBLIGATION/PERSON/resource in the graph."""
    explanation: str
    confidence: float
    from_deterministic_prepass: bool
    """True for a collision the cheap deterministic pre-pass caught on its
    own (exact same-person/overlapping-window arithmetic) before any
    Gemini call — see `conflict_radar.py`'s module docstring for the E1
    `backend/app/solvers/` integration point this pre-pass stands in
    for."""


# ---------------------------------------------------------------------------
# A16 — Constraint Learner output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateConstraint:
    """A detected repeated signal suggesting a new implicit household
    constraint (spec §15.4 A16). **Never a real
    `contracts.graph_types.Constraint` node** — `status` only ever takes
    the one value below, structurally: there is no code path in this
    package that can turn a `CandidateConstraint` into a written hard
    constraint without going through a human confirmation gate this phase
    does not itself implement the UI for (Phase 5+), matching A16's
    explicit forbidden rule: "writing a hard constraint without human
    confirmation." This dataclass IS that gate's data shape — the gating
    is enforced by this type never offering a "confirmed" value to set."""

    pending_id: str
    kind: ConstraintKind
    severity_if_confirmed: ConstraintSeverity
    structured: dict[str, str]
    original_text_examples: tuple[str, ...]
    supporting_source_document_ids: tuple[NodeId, ...]
    support_count: int
    confidence: float
    status: Literal["pending_confirmation"] = "pending_confirmation"


# ---------------------------------------------------------------------------
# A15 — Obligation Writer output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What happened when A15 tried to persist one candidate."""

    candidate_id: str
    node_id: NodeId | None
    """The written (or matched-existing) OBLIGATION's id. `None` only if
    the candidate was rejected outright (e.g. a hard-constraint violation
    that was never cleared) and nothing was written."""
    action: Literal["written", "deduplicated", "superseded", "rejected"]
    detail: str


__all__ = [
    "CandidateConstraint",
    "ConflictFinding",
    "ConflictKind",
    "ConstraintCheckFinding",
    "DiscardedInference",
    "HouseholdContext",
    "ImpliedObligationCandidate",
    "ImplicationRequest",
    "ImplicationRunResult",
    "WriteOutcome",
]

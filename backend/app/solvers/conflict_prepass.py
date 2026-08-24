"""Deterministic conflict pre-pass (PHASES.md Phase 4, E1 work item 1;
spec §7.3 Stage 3 — DECONFLICT).

**No LLM call anywhere in this module.** A14 (Conflict Radar, E2) is
expected to run `DeterministicConflictPrepass.run` *before* spending a
Pro-tier reasoning call — this catches the mechanically-detectable cases
(temporal, resource, capability, load — spec §7.3's own conflict-type
list) cheaply, so the reasoning pass only has to reason about what a code
query genuinely cannot resolve. A14 may confirm, refine, or reason further
about anything this module returns; this module never writes to the graph
itself (no `conflicts_with`/`violates` edges) — it returns structured
candidates for a caller with write access and reasoning judgement to act
on, matching spec §5.7's `conflicts(scope)` being a *read* over edges
someone else already wrote.

## What each conflict type checks, and against which real `Obligation`/
## `Person` fields (contracts/graph_types.py, frozen — never invented here)

- **Temporal**: two OBLIGATIONs `owned_by` the same PERSON with
  overlapping *activity windows*. `Obligation` has no explicit start time
  or location/travel-time field — the window is derived from the only two
  time-shaped fields it actually has: `[due_at - effort_estimate_minutes,
  due_at]` (a zero-width point at `due_at` when `effort_estimate_minutes`
  is `None`). Travel-time buffering (spec §7.3's worked example gestures
  at this for the ATM-stop implication) is **not implemented** — there is
  no location field on `Obligation` to buffer around; see this module's
  final report for the corresponding contract-gap note.
- **Resource**: two OBLIGATIONs needing the same singular resource (e.g.
  "the car") at overlapping times. **`Obligation` has no field expressing
  required-resource identity, and no edge/metadata convention for it
  exists anywhere in the codebase today** (verified by grep across
  `backend/app/` before writing this module — no existing convention to
  honour). This is a real contract gap, not a heuristic this module
  invents: resource-conflict detection is wired via an injectable
  `ResourceIdentityResolver` that the caller must supply from some other
  source of truth; with none supplied (the default), detection is a
  documented no-op (`ConflictPrepassResult.resource_detection_skipped`),
  never a silent guess off obligation titles.
- **Capability**: an OBLIGATION's owner (`owned_by` edge) lacking a
  needed `Person` capability flag (`can_drive`, `can_sign`,
  `has_bank_access`, `has_medical_proxy` — all real fields). `Obligation`
  has no structured "required capability" field either (only a free-text
  `obligation_type`), so the type-string -> capability mapping is also
  injectable (`capability_requirements`), defaulting to the single
  mapping spec §5.4.2 states explicitly: `permission_slip` requires
  `can_sign` ("Signing authority matters") — confirmed against
  `app/agents/intake/strategies/permission_slip_strategy.py`'s own
  docstring, not guessed.
- **Load**: `GraphReader.load(person, window)` (Phase 1, hardened this
  phase — `app/graph/reader.py`) exceeding a fairness threshold. This
  module adds only the threshold-comparison step on top of that existing
  traversal, per the E1 charter's explicit instruction not to rebuild a
  primitive that already works.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import combinations
from typing import Literal, Protocol

import structlog
from contracts.graph_types import EdgeType, NodeId, Obligation, Person
from contracts.repositories import GraphReader

logger = structlog.get_logger(__name__)

CapabilityFlag = Literal["can_drive", "can_sign", "has_bank_access", "has_medical_proxy"]
"""The four `Person` capability flags spec §5.2/§7.3 name explicitly."""

_DEFAULT_CAPABILITY_REQUIREMENTS: Mapping[str, CapabilityFlag] = {
    "permission_slip": "can_sign",
}
"""The only `Obligation.obligation_type -> required Person capability`
mapping this module asserts by default, and it is deliberately narrow.
`contracts.graph_types.Obligation` carries no structured "required
capability" field, so any type-string -> capability mapping is domain
knowledge this module does not own — inventing a broad keyword-matching
table here would be exactly the kind of ungrounded heuristic the E1
charter warns against for the resource case. This one entry is the sole
mapping spec §5.4.2 itself makes explicit ("Signing authority matters" for
PERMISSION_SLIP), and it matches the literal `obligation_type` string
`app/agents/intake/strategies/permission_slip_strategy.py` already writes.
Callers with more domain knowledge (E2) supply the rest via
`capability_requirements`."""


class ConflictType(StrEnum):
    """Spec §7.3 Stage 3's own four conflict-type names."""

    TEMPORAL = "temporal"
    RESOURCE = "resource"
    CAPABILITY = "capability"
    LOAD = "load"


@dataclass(frozen=True, slots=True)
class TemporalConflict:
    """Two OBLIGATIONs owned by the same PERSON with overlapping activity
    windows — spec §7.3's canonical example: a 1:30pm early pickup against
    a 1:00pm work meeting."""

    conflict_type: Literal[ConflictType.TEMPORAL]
    person_id: NodeId
    obligation_a_id: NodeId
    obligation_b_id: NodeId
    window_a: tuple[datetime, datetime]
    window_b: tuple[datetime, datetime]
    overlap: tuple[datetime, datetime]
    detail: str


@dataclass(frozen=True, slots=True)
class ResourceConflict:
    """Two OBLIGATIONs requiring the same singular resource at overlapping
    times, per a caller-supplied `ResourceIdentityResolver`."""

    conflict_type: Literal[ConflictType.RESOURCE]
    resource_key: str
    obligation_a_id: NodeId
    obligation_b_id: NodeId
    window_a: tuple[datetime, datetime]
    window_b: tuple[datetime, datetime]
    overlap: tuple[datetime, datetime]
    detail: str


@dataclass(frozen=True, slots=True)
class CapabilityConflict:
    """An OBLIGATION's owner lacks the `Person` capability flag it needs."""

    conflict_type: Literal[ConflictType.CAPABILITY]
    person_id: NodeId
    obligation_id: NodeId
    missing_capability: CapabilityFlag
    detail: str


@dataclass(frozen=True, slots=True)
class LoadConflict:
    """A PERSON's `load()` in a window exceeds a fairness threshold —
    hands off to the Fair Allocator (spec §7.3 Stage 3)."""

    conflict_type: Literal[ConflictType.LOAD]
    person_id: NodeId
    window: tuple[datetime, datetime]
    load_minutes: float
    threshold_minutes: float
    exceeded_by_minutes: float
    detail: str


ConflictCandidate = TemporalConflict | ResourceConflict | CapabilityConflict | LoadConflict


class ResourceIdentityResolver(Protocol):
    """Injected by the caller — this module owns no source of truth for
    "what singular resource does this obligation require," because
    `contracts.graph_types.Obligation` has no field for it (see this
    module's docstring)."""

    def resolve(self, obligation: Obligation) -> str | None:
        """Returns a stable resource-identity key (e.g. `"vehicle:family-
        car"`) this obligation requires exclusive use of, or `None` if it
        requires no singular shared resource."""
        ...


@dataclass(frozen=True, slots=True)
class ConflictPrepassResult:
    """Structured candidates a reasoning agent (A14) can confirm, refine,
    or reason further about — never applied to the graph directly by this
    module."""

    temporal: tuple[TemporalConflict, ...]
    resource: tuple[ResourceConflict, ...]
    capability: tuple[CapabilityConflict, ...]
    load: tuple[LoadConflict, ...]
    resource_detection_skipped: bool
    """`True` whenever no `ResourceIdentityResolver` was supplied to
    `DeterministicConflictPrepass` — see this module's docstring: this is
    an honest "detection not possible with the current contract," not a
    silent zero-conflicts result to be mistaken for "checked, none
    found."""

    def all_candidates(self) -> tuple[ConflictCandidate, ...]:
        """Every candidate across all four conflict types, in a stable
        temporal -> resource -> capability -> load order."""
        return (*self.temporal, *self.resource, *self.capability, *self.load)


def _activity_window(obligation: Obligation) -> tuple[datetime, datetime] | None:
    """The best-grounded activity window `Obligation`'s actual fields
    support: `[due_at - effort_estimate_minutes, due_at]`, or a zero-width
    point at `due_at` when no effort estimate exists. `None` if the
    obligation has no `due_at` at all — nothing to check it against."""
    if obligation.due_at is None:
        return None
    if obligation.effort_estimate_minutes and obligation.effort_estimate_minutes > 0:
        start = obligation.due_at - timedelta(minutes=obligation.effort_estimate_minutes)
    else:
        start = obligation.due_at
    return (start, obligation.due_at)


def _overlap(
    window_a: tuple[datetime, datetime], window_b: tuple[datetime, datetime]
) -> tuple[datetime, datetime] | None:
    """Strict interval overlap: touching endpoints (one window ending
    exactly when another begins) are adjacent, not overlapping. Returns
    the overlapping sub-interval, or `None` if the windows do not
    overlap."""
    a_start, a_end = window_a
    b_start, b_end = window_b
    if a_start < b_end and b_start < a_end:
        return (max(a_start, b_start), min(a_end, b_end))
    return None


def _pairs(items: Sequence[Obligation]) -> Iterator[tuple[Obligation, Obligation]]:
    return combinations(items, 2)


class DeterministicConflictPrepass:
    """Code-only conflict detector — no LLM call anywhere in this class.
    Dependency-injected on a `contracts.repositories.GraphReader` (T0,
    read-only) for owner resolution (`neighbours`) and load computation
    (`load`); never a Firestore client directly (hexagonal architecture,
    PHASES.md §2.2)."""

    def __init__(
        self,
        graph_reader: GraphReader,
        *,
        resource_identity_resolver: ResourceIdentityResolver | None = None,
        capability_requirements: Mapping[str, CapabilityFlag] = _DEFAULT_CAPABILITY_REQUIREMENTS,
    ) -> None:
        self._reader = graph_reader
        self._resource_identity_resolver = resource_identity_resolver
        self._capability_requirements = capability_requirements

    def run(
        self,
        obligations: Sequence[Obligation],
        *,
        fairness_threshold_minutes: float,
        load_window: tuple[datetime, datetime],
    ) -> ConflictPrepassResult:
        """Runs all four deterministic conflict checks over `obligations`
        (the candidate set A14 wants pre-screened — typically newly
        implied obligations plus the affected person's other open
        obligations, per spec §7.3 Stage 3: "check against ... existing
        obligations").

        Args:
            obligations: candidate OBLIGATIONs to check, pairwise and
                individually.
            fairness_threshold_minutes: load-conflict threshold, in
                minutes of `effort_estimate_minutes` within `load_window`.
            load_window: the time window `load()` is evaluated over for
                every person who owns at least one of `obligations`.

        Returns:
            A `ConflictPrepassResult` bundling every candidate found,
            grouped by type.
        """
        owners_by_obligation = self._owners_by_obligation(obligations)
        temporal = self._detect_temporal(obligations, owners_by_obligation)
        resource = self._detect_resource(obligations)
        capability = self._detect_capability(obligations, owners_by_obligation)
        load = self._detect_load(owners_by_obligation, fairness_threshold_minutes, load_window)
        result = ConflictPrepassResult(
            temporal=temporal,
            resource=resource,
            capability=capability,
            load=load,
            resource_detection_skipped=self._resource_identity_resolver is None,
        )
        logger.info(
            "conflict_prepass.completed",
            obligation_count=len(obligations),
            temporal_count=len(temporal),
            resource_count=len(resource),
            capability_count=len(capability),
            load_count=len(load),
            resource_detection_skipped=result.resource_detection_skipped,
        )
        return result

    def _owners_by_obligation(self, obligations: Sequence[Obligation]) -> dict[NodeId, tuple[Person, ...]]:
        owners: dict[NodeId, tuple[Person, ...]] = {}
        for obligation in obligations:
            neighbours = self._reader.neighbours(obligation.id, EdgeType.OWNED_BY)
            owners[obligation.id] = tuple(n for n in neighbours if isinstance(n, Person))
        return owners

    def _detect_temporal(
        self,
        obligations: Sequence[Obligation],
        owners_by_obligation: Mapping[NodeId, tuple[Person, ...]],
    ) -> tuple[TemporalConflict, ...]:
        by_person: dict[NodeId, list[Obligation]] = {}
        for obligation in obligations:
            for owner in owners_by_obligation.get(obligation.id, ()):
                by_person.setdefault(owner.id, []).append(obligation)

        found: list[TemporalConflict] = []
        for person_id, owned in by_person.items():
            for obligation_a, obligation_b in _pairs(owned):
                window_a = _activity_window(obligation_a)
                window_b = _activity_window(obligation_b)
                if window_a is None or window_b is None:
                    continue
                overlap = _overlap(window_a, window_b)
                if overlap is None:
                    continue
                found.append(
                    TemporalConflict(
                        conflict_type=ConflictType.TEMPORAL,
                        person_id=person_id,
                        obligation_a_id=obligation_a.id,
                        obligation_b_id=obligation_b.id,
                        window_a=window_a,
                        window_b=window_b,
                        overlap=overlap,
                        detail=(
                            f"'{obligation_a.title}' and '{obligation_b.title}' both require the same "
                            f"person between {overlap[0].isoformat()} and {overlap[1].isoformat()}"
                        ),
                    )
                )
        return tuple(found)

    def _detect_resource(self, obligations: Sequence[Obligation]) -> tuple[ResourceConflict, ...]:
        if self._resource_identity_resolver is None:
            logger.info(
                "conflict_prepass.resource_detection_skipped",
                reason=(
                    "no ResourceIdentityResolver injected; contracts.graph_types.Obligation has no field "
                    "expressing required-resource identity (real contract gap, not a missing feature here)"
                ),
            )
            return ()

        by_resource: dict[str, list[Obligation]] = {}
        for obligation in obligations:
            key = self._resource_identity_resolver.resolve(obligation)
            if key is not None:
                by_resource.setdefault(key, []).append(obligation)

        found: list[ResourceConflict] = []
        for resource_key, group in by_resource.items():
            for obligation_a, obligation_b in _pairs(group):
                window_a = _activity_window(obligation_a)
                window_b = _activity_window(obligation_b)
                if window_a is None or window_b is None:
                    continue
                overlap = _overlap(window_a, window_b)
                if overlap is None:
                    continue
                found.append(
                    ResourceConflict(
                        conflict_type=ConflictType.RESOURCE,
                        resource_key=resource_key,
                        obligation_a_id=obligation_a.id,
                        obligation_b_id=obligation_b.id,
                        window_a=window_a,
                        window_b=window_b,
                        overlap=overlap,
                        detail=(
                            f"'{obligation_a.title}' and '{obligation_b.title}' both require resource "
                            f"'{resource_key}' between {overlap[0].isoformat()} and {overlap[1].isoformat()}"
                        ),
                    )
                )
        return tuple(found)

    def _detect_capability(
        self,
        obligations: Sequence[Obligation],
        owners_by_obligation: Mapping[NodeId, tuple[Person, ...]],
    ) -> tuple[CapabilityConflict, ...]:
        found: list[CapabilityConflict] = []
        for obligation in obligations:
            required_flag = self._capability_requirements.get(obligation.obligation_type)
            if required_flag is None:
                continue
            for owner in owners_by_obligation.get(obligation.id, ()):
                if not getattr(owner, required_flag):
                    found.append(
                        CapabilityConflict(
                            conflict_type=ConflictType.CAPABILITY,
                            person_id=owner.id,
                            obligation_id=obligation.id,
                            missing_capability=required_flag,
                            detail=(
                                f"'{obligation.title}' requires '{required_flag}' but its owner "
                                f"'{owner.display_name}' does not have it"
                            ),
                        )
                    )
        return tuple(found)

    def _detect_load(
        self,
        owners_by_obligation: Mapping[NodeId, tuple[Person, ...]],
        fairness_threshold_minutes: float,
        load_window: tuple[datetime, datetime],
    ) -> tuple[LoadConflict, ...]:
        person_ids: set[NodeId] = set()
        for owners in owners_by_obligation.values():
            person_ids.update(owner.id for owner in owners)

        found: list[LoadConflict] = []
        for person_id in sorted(person_ids):
            load_minutes = self._reader.load(person_id, load_window)
            if load_minutes > fairness_threshold_minutes:
                found.append(
                    LoadConflict(
                        conflict_type=ConflictType.LOAD,
                        person_id=person_id,
                        window=load_window,
                        load_minutes=load_minutes,
                        threshold_minutes=fairness_threshold_minutes,
                        exceeded_by_minutes=load_minutes - fairness_threshold_minutes,
                        detail=(
                            f"person {person_id} has {load_minutes:.0f} minutes of obligation load in "
                            f"the window, exceeding the {fairness_threshold_minutes:.0f}-minute fairness "
                            f"threshold by {load_minutes - fairness_threshold_minutes:.0f} minutes"
                        ),
                    )
                )
        return tuple(found)


__all__ = [
    "CapabilityConflict",
    "CapabilityFlag",
    "ConflictCandidate",
    "ConflictPrepassResult",
    "ConflictType",
    "DeterministicConflictPrepass",
    "LoadConflict",
    "ResourceConflict",
    "ResourceIdentityResolver",
    "TemporalConflict",
]

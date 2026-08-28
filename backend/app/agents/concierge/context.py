"""Real-graph assembly for the Outbound Concierge (A50, A52 — spec §13,
§15.10, PHASES.md Phase 10, ADR-016) — E2's half of
`backend/app/agents/concierge/`.

Two real, structural jobs live here, kept separate from each agent's own
pure reasoning logic (hexagonal architecture: an agent's core logic never
imports `contracts.repositories.GraphReader` machinery directly for
multi-hop assembly like this; mirrors `app.agents.fair_allocator.
context`'s established role for A18/A21 exactly, two phases later):

1. `resolve_known_facts` — the real graph-first check spec §13.2 Step 1
   describes ("the agent does not interrogate — it queries the graph
   first and asks only what it cannot infer"), made structural: A50
   (`requirement_clarifier_agent.py`) is never even shown a requirement
   this function could resolve as something it might ask about.
2. `resolve_reliability_signal` — ADR-016's formal `Outcome.
   attribution_tags` provider-reliability convention, walked via
   `booked_with` (OBLIGATION -> PROVIDER) then that obligation's
   `completes_into` OUTCOME, for A52's real prior-experience weighting.
"""

from __future__ import annotations

from datetime import datetime

from contracts.graph_types import (
    Constraint,
    ConstraintKind,
    EdgeType,
    NodeId,
    Obligation,
    ObligationStatus,
    Outcome,
    Provider,
)
from contracts.repositories import GraphReader

from .types import GraphKnownFact, ProviderReliabilitySignal

SERVICE_CATEGORY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "dental": (
        "person_availability",
        "prior_provider_history",
        "last_visit_date",
        "insurance_provider",
        "situation_urgency",
        "date_constraints",
        "provider_preference",
    ),
    "default": (
        "person_availability",
        "situation_urgency",
        "date_constraints",
    ),
}
"""Per-service-category requirement checklist. `"dental"` enumerates
exactly spec §13.2 Step 1's own worked dentist example as seven real
requirement keys: four are real graph-resolvable facts ("who it's for,
their availability model, the last visit date, insurance details, past
provider history"), the other three ("is this routine or is something
hurting? any preference for the previous clinic? any date constraints?")
are spec's own "genuinely unknown, so asked" examples — see
`_ALWAYS_ASK_REQUIREMENTS` below for why no resolver is attempted for
those. `"default"` is the real fallback for any category with no
dedicated checklist yet — never an empty tuple, since availability,
urgency, and date constraints are worth checking for any service booking.
Extended by later phases as new service categories are wired."""

_ALWAYS_ASK_REQUIREMENTS: frozenset[str] = frozenset(
    {"situation_urgency", "date_constraints", "provider_preference"}
)
"""Requirement keys that are, by their nature, never resolvable from the
graph — they concern *this specific, new* request (is this one routine
or urgent? what date constraint applies to it this time? does the
household actually want the same provider as before?), not a standing
fact the graph could hold about the household. No resolver function
exists for these — writing one would not close a gap, it would be
guessing at something the graph cannot in principle contain. Spec §13.2
Step 1 names exactly these three as genuinely unknown even in a
household with rich prior history."""


def _schedule_known_fact(reader: GraphReader, *, person_id: NodeId) -> GraphKnownFact:
    """Real, always-resolvable — spec §13.2's "their availability model"
    known-fact. A person with zero `SCHEDULE`-kind constraints on file is
    a real, positive fact ("no known restriction"), not an unknown — this
    mirrors `app.agents.intention_action.schedule_parsing.
    person_availability_for_window`'s established open-world convention:
    absence of evidence is evidence of availability, not of ignorance."""
    constraints = [
        c for c in reader.neighbours(person_id, EdgeType.CONSTRAINS) if isinstance(c, Constraint)
    ]
    schedule_constraints = [c for c in constraints if c.kind is ConstraintKind.SCHEDULE]
    if not schedule_constraints:
        return GraphKnownFact(
            field="person_availability",
            value="no schedule constraint on file for this person — treated as generally available",
            source="neighbours(person_id, CONSTRAINS) — no SCHEDULE-kind constraint found",
        )
    summary = "; ".join(c.original_text for c in schedule_constraints)
    return GraphKnownFact(
        field="person_availability", value=summary, source="neighbours(person_id, CONSTRAINS)"
    )


def _insurance_known_fact(reader: GraphReader, *, person_id: NodeId) -> GraphKnownFact | None:
    """Real, sometimes-resolvable — spec §13.2's "insurance details"
    known-fact, read from a `Constraint.structured['insurance_provider']`
    entry when one exists. Genuinely absent from many households' graphs
    (not every household has recorded this) — `None` is a real, honest
    "not on file", never a guessed default."""
    constraints = [
        c for c in reader.neighbours(person_id, EdgeType.CONSTRAINS) if isinstance(c, Constraint)
    ]
    for constraint in constraints:
        insurer = constraint.structured.get("insurance_provider")
        if insurer:
            return GraphKnownFact(
                field="insurance_provider",
                value=insurer,
                source=f"Constraint {constraint.id}.structured['insurance_provider']",
            )
    return None


def _category_obligations(
    reader: GraphReader, *, person_id: NodeId, service_category: str
) -> tuple[Obligation, ...]:
    owned = [o for o in reader.neighbours(person_id, EdgeType.OWNED_BY) if isinstance(o, Obligation)]
    return tuple(o for o in owned if o.obligation_type == service_category)


def _last_visit_known_fact(obligations: tuple[Obligation, ...]) -> GraphKnownFact | None:
    """Real, sometimes-resolvable — spec §13.2's "the last visit date"
    known-fact. `Obligation.due_at` on the most recent COMPLETED
    obligation of this `service_category` stands in for "the last visit
    date" — `Outcome.actual`/`predicted` are free text with no structured
    date field, so the obligation's own scheduled date is the real,
    structured signal this codebase actually has for "when did this last
    happen." `None` when this household has no completed obligation of
    this category on file at all — never guessed."""
    completed_with_date: list[tuple[Obligation, datetime]] = [
        (obligation, obligation.due_at)
        for obligation in obligations
        if obligation.status is ObligationStatus.COMPLETED and obligation.due_at is not None
    ]
    if not completed_with_date:
        return None
    most_recent_obligation, most_recent_date = max(completed_with_date, key=lambda pair: pair[1])
    return GraphKnownFact(
        field="last_visit_date",
        value=most_recent_date.isoformat(),
        source=f"Obligation {most_recent_obligation.id}.due_at (status=completed)",
    )


def _prior_provider_known_fact(
    reader: GraphReader, obligations: tuple[Obligation, ...]
) -> GraphKnownFact | None:
    """Real, sometimes-resolvable — spec §13.2's "past provider history"
    known-fact, via `neighbours(obligation.id, BOOKED_WITH)` for this
    household's own completed obligations of this category. Deliberately
    distinct from the `"provider_preference"` always-ask requirement:
    knowing *who* the prior provider was is a graph fact; whether the
    household *wants* that same provider again is a preference the graph
    cannot hold (see `_ALWAYS_ASK_REQUIREMENTS`)."""
    for obligation in obligations:
        providers = [
            p for p in reader.neighbours(obligation.id, EdgeType.BOOKED_WITH) if isinstance(p, Provider)
        ]
        if providers:
            provider = providers[0]
            return GraphKnownFact(
                field="prior_provider_history",
                value=f"{provider.name} (provider {provider.id})",
                source=f"neighbours(obligation {obligation.id}, BOOKED_WITH)",
            )
    return None


def resolve_known_facts(
    reader: GraphReader, *, person_id: NodeId, service_category: str
) -> tuple[tuple[GraphKnownFact, ...], tuple[str, ...]]:
    """The real graph-first check spec §13.2 Step 1 describes: for every
    requirement `service_category` genuinely needs, attempts a real
    resolution against the household graph first; only what a real query
    could not answer becomes a `candidate_unknowns` entry A50 is even
    allowed to consider asking about.

    Args:
        reader: the household's `GraphReader`.
        person_id: who the service is for.
        service_category: e.g. `"dental"` — looked up in
            `SERVICE_CATEGORY_REQUIREMENTS`, falling back to
            `SERVICE_CATEGORY_REQUIREMENTS["default"]` for an
            unregistered category.

    Returns:
        `(known_facts, candidate_unknowns)` — every requirement key in
        this category's checklist ends up in exactly one of the two,
        never both, never neither.

    Raises:
        ValueError: `SERVICE_CATEGORY_REQUIREMENTS` names a requirement
            key with no registered resolver and not in
            `_ALWAYS_ASK_REQUIREMENTS` — a defect in the checklist table
            itself, never guessed at silently.
    """
    checklist = SERVICE_CATEGORY_REQUIREMENTS.get(service_category, SERVICE_CATEGORY_REQUIREMENTS["default"])
    obligations = _category_obligations(reader, person_id=person_id, service_category=service_category)

    known: list[GraphKnownFact] = []
    unknowns: list[str] = []

    for requirement in checklist:
        if requirement in _ALWAYS_ASK_REQUIREMENTS:
            unknowns.append(requirement)
        elif requirement == "person_availability":
            known.append(_schedule_known_fact(reader, person_id=person_id))
        elif requirement == "insurance_provider":
            insurance_fact = _insurance_known_fact(reader, person_id=person_id)
            (known.append(insurance_fact) if insurance_fact is not None else unknowns.append(requirement))
        elif requirement == "last_visit_date":
            visit_fact = _last_visit_known_fact(obligations)
            (known.append(visit_fact) if visit_fact is not None else unknowns.append(requirement))
        elif requirement == "prior_provider_history":
            provider_fact = _prior_provider_known_fact(reader, obligations)
            (known.append(provider_fact) if provider_fact is not None else unknowns.append(requirement))
        else:
            raise ValueError(f"no resolver registered for requirement {requirement!r}")

    return tuple(known), tuple(unknowns)


def resolve_reliability_signal(
    reader: GraphReader, *, provider_id: NodeId
) -> ProviderReliabilitySignal | None:
    """Real prior-household-experience lookup for one existing provider —
    ADR-016's formal `Outcome.attribution_tags` convention, walked via
    `booked_with` (OBLIGATION -> PROVIDER) then that obligation's
    `completes_into` OUTCOME, never free-text pattern-matching.

    Args:
        reader: the household's `GraphReader`.
        provider_id: an existing `Provider` node's real id (only
            meaningful for `ProviderCandidate.is_existing_household_
            provider=True` candidates — a freshly-discovered provider has
            no graph history to walk at all).

    Returns:
        `None` when this household has no `booked_with` history with
        this provider at all (never booked, or booked but with no
        `completes_into` `Outcome` recorded yet) — A52 treats `None` as
        "no prior-experience signal available," never as a synthetic
        zero/neutral score.
    """
    obligations = [
        o for o in reader.neighbours(provider_id, EdgeType.BOOKED_WITH) if isinstance(o, Obligation)
    ]
    if not obligations:
        return None

    no_show = on_time = rescheduled = unresponsive = total = 0
    for obligation in obligations:
        for outcome in reader.history(obligation.id):
            if not isinstance(outcome, Outcome):
                continue
            total += 1
            tags = set(outcome.attribution_tags)
            if "no_show" in tags:
                no_show += 1
            if "on_time" in tags:
                on_time += 1
            if "rescheduled" in tags:
                rescheduled += 1
            if "unresponsive_to_automated_caller" in tags:
                unresponsive += 1

    if total == 0:
        return None

    return ProviderReliabilitySignal(
        provider_id=provider_id,
        no_show_count=no_show,
        on_time_count=on_time,
        rescheduled_count=rescheduled,
        unresponsive_count=unresponsive,
        total_outcomes_considered=total,
    )


__all__ = [
    "SERVICE_CATEGORY_REQUIREMENTS",
    "resolve_known_facts",
    "resolve_reliability_signal",
]

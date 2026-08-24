"""Real-graph assembly of `types.HouseholdContext` and
`types.ImplicationRequest` — the "read via GraphReader" side of A12's
input, kept separate from `implication_agent.py`'s pure reasoning logic
(hexagonal architecture: the agent's core logic never imports
`RawPayloadStore`/Firestore machinery directly; only this module does).

**Contract-gap note (raised, not routed around):** spec §5.2 describes an
"availability model" as part of PERSON, but the frozen
`contracts.graph_types.Person` dataclass has no such field — only role and
boolean capability flags (`can_drive`, `can_sign`, ...). This module (and
`obligation_writer.py`'s must-start-by computation) approximates a
person's availability from what the frozen contract actually offers:
SCHEDULE-kind `Constraint` nodes and existing `Obligation`s the person
owns. This is a real, documented scope decision, not a silent
workaround — see the Phase 4 final report for the corresponding
`docs/DEBT.md` candidate raised to the CTO.
"""

from __future__ import annotations

from contracts.graph_types import (
    Constraint,
    EdgeType,
    NodeId,
    Obligation,
    ObligationStatus,
    Person,
    SourceDocument,
)
from contracts.repositories import GraphReader

from app.persistence.raw_payload_store import RawPayloadStore

from .errors import SourceDocumentNotResolvable
from .types import HouseholdContext, ImplicationRequest

_DEFAULT_CONTEXT_DEPTH = 4
"""`blast_radius` depth used to gather "everything nearby" a SOURCE_DOCUMENT
(people, constraints, other open obligations). Chosen to comfortably cover
the household-graph shape spec §7.3's worked example implies: SOURCE_DOCUMENT
-[states]-> OBLIGATION -[benefits]-> PERSON <-[constrains]- CONSTRAINT is 3
hops; SOURCE_DOCUMENT -> ... -> PERSON <-[owned_by]- (a different, sibling)
OBLIGATION is 4 hops. A documented, revisitable constant — not a magic
number sprinkled at each call site."""

_CLOSED_OBLIGATION_STATUSES = (
    ObligationStatus.COMPLETED,
    ObligationStatus.DROPPED,
    ObligationStatus.SUPERSEDED,
)


def gather_household_context(reader: GraphReader, *, source_document_id: NodeId) -> HouseholdContext:
    """Assembles the household context A12/A13/A14/A16 reason against,
    using only `contracts.repositories.GraphReader` operations (spec §5.7)
    — `neighbours` for the precise "what did this exact document state"
    list, `blast_radius` for the fuzzier "what else is nearby" list, since
    `GraphReader` has no "list all household nodes of type X" primitive
    (see this module's docstring).

    Args:
        reader: the household's `GraphReader`.
        source_document_id: the SOURCE_DOCUMENT node id A12 is reasoning
            about.

    Returns:
        A `HouseholdContext` — `stated_obligations` precise, the rest
        best-effort within `_DEFAULT_CONTEXT_DEPTH` hops.
    """
    stated = tuple(
        node
        for node in reader.neighbours(source_document_id, EdgeType.STATES)
        if isinstance(node, Obligation)
    )
    stated_ids = {obligation.id for obligation in stated}

    nearby = reader.blast_radius(source_document_id, _DEFAULT_CONTEXT_DEPTH)
    people = tuple(node for node in nearby if isinstance(node, Person))
    constraints = tuple(node for node in nearby if isinstance(node, Constraint))
    open_obligations = tuple(
        node
        for node in nearby
        if isinstance(node, Obligation)
        and node.id not in stated_ids
        and node.status not in _CLOSED_OBLIGATION_STATUSES
    )

    return HouseholdContext(
        people=people,
        constraints=constraints,
        open_obligations=open_obligations,
        stated_obligations=stated,
    )


def assemble_implication_request(
    reader: GraphReader,
    payload_store: RawPayloadStore,
    *,
    source_document_id: NodeId,
) -> ImplicationRequest:
    """Builds a complete `ImplicationRequest` for a real SOURCE_DOCUMENT
    already in the graph: resolves its raw text via `RawPayloadStore` and
    its household context via `gather_household_context`.

    Args:
        reader: the household's `GraphReader`.
        payload_store: resolves the SOURCE_DOCUMENT's `raw_payload_ref` to
            real bytes.
        source_document_id: the SOURCE_DOCUMENT to reason about.

    Raises:
        SourceDocumentNotResolvable: `source_document_id` does not resolve
            to a current `SourceDocument` node, or its payload does not
            decode as UTF-8 text — Phase 4's implication reasoning is
            text-shaped-document-only (email, chat export, notice); an
            image/PDF-shaped SOURCE_DOCUMENT is out of scope for A12 (its
            *stated* obligations were already extracted multimodally by
            A3/A3b in Phase 3; deriving further implications from a
            rendered image is future work, not silently attempted here).
    """
    node = reader.get_node(source_document_id)
    if not isinstance(node, SourceDocument):
        raise SourceDocumentNotResolvable(
            source_document_id=str(source_document_id), reason="no current SOURCE_DOCUMENT node found"
        )

    payload = payload_store.retrieve(node.raw_payload_ref)
    try:
        document_text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceDocumentNotResolvable(
            source_document_id=str(source_document_id),
            reason=(
                "raw payload is not UTF-8 text (image/PDF-shaped documents "
                f"are out of A12's scope): {exc}"
            ),
        ) from exc

    household_context = gather_household_context(reader, source_document_id=source_document_id)
    return ImplicationRequest(
        source_document_id=source_document_id,
        document_text=document_text,
        household_context=household_context,
    )


__all__ = ["assemble_implication_request", "gather_household_context"]

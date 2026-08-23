"""Shared helpers for the fourteen `ExtractionStrategy` implementations
(spec §5.4, ADR-008). Not itself a strategy — pure helpers to avoid
repeating the same field-lookup / provenance-construction / id-minting
boilerplate fourteen times.

**Node/edge id minting:** every strategy mints its own node/edge ids
(`new_node_id`, `new_edge_id`) at map-time — a strategy never queries the
graph for an id (it has no `GraphReader`, per ADR-008's `map_to_graph`
signature). Ids are content-free random hex, not sequential — this
codebase's `NodeId`/`EdgeId` are opaque strings everywhere else too
(`app.persistence.raw_payload_store`'s content-addressed refs are the one
deliberate exception, for a different reason).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    EdgeId,
    ExtractedField,
    NodeId,
    Provenance,
    SourceRef,
)

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def field_by_name(fields: tuple[ExtractedField, ...], name: str) -> ExtractedField | None:
    """Returns the first `ExtractedField` named `name`, or `None` if A3
    did not extract it (a genuinely missing optional field, or a required
    field that fell below its confidence floor and was still surfaced as
    `Derivation.AMBIGUOUS` — callers decide per-field whether an
    `AMBIGUOUS` value is usable for a given node's purposes)."""
    for field in fields:
        if field.name == name:
            return field
    return None


def provenance_for(
    field: ExtractedField,
    *,
    source_document_id: NodeId,
    deriving_agent: AgentId,
    clock: datetime | None = None,
) -> Provenance:
    """Builds a `Provenance` for a node/edge derived directly from one
    `ExtractedField` — carries the field's own `derivation`/`confidence`
    forward unchanged (a strategy never upgrades an `AMBIGUOUS` field to
    `EXTRACTED` just because it needs a value to build a node; the node
    it builds stays tagged `AMBIGUOUS` too)."""
    return Provenance(
        derivation=field.derivation,
        source_ref=SourceRef(source_document_id=source_document_id, region=field.source_region),
        confidence=field.confidence,
        deriving_agent=deriving_agent,
        created_at=clock or datetime.now(UTC),
    )


def new_node_id(prefix: str) -> NodeId:
    return NodeId(f"{prefix}:{uuid.uuid4().hex}")


def new_edge_id() -> EdgeId:
    return EdgeId(uuid.uuid4().hex)


def slugify(text: str) -> str:
    """Lowercase, non-alphanumeric-collapsed slug — used to mint a
    deterministic pseudo-id for an entity a strategy names but does not
    itself resolve/create (e.g. a receipt's merchant -> a VENDOR-shaped
    id). Deterministic (same input -> same slug) so the same merchant
    string always mints the same placeholder id across multiple receipts,
    even before real entity resolution (A5's job, or a future VENDOR
    resolution agent) replaces it with a confirmed VENDOR node id."""
    return _SLUG_PATTERN.sub("-", text.strip().lower()).strip("-") or "unknown"


def cadence_from_period(start: object, end: object) -> str:
    """Buckets the gap between two extracted date/datetime field values
    into a human-readable cadence label — deterministic arithmetic over
    literal extracted data (never a guess): `utility_bill_strategy.py`
    (billing period) and `insurance_document_strategy.py` (premium due
    date -> renewal date) both use this for their `RECURRING_COMMITMENT.
    cadence`."""
    start_dt = parse_date_value(start)
    end_dt = parse_date_value(end)
    if start_dt is None or end_dt is None:
        return "unknown"
    days = (end_dt - start_dt).days
    if 25 <= days <= 35:
        return "monthly"
    if 55 <= days <= 65:
        return "bimonthly"
    if 85 <= days <= 95:
        return "quarterly"
    if 175 <= days <= 190:
        return "half_yearly"
    if 350 <= days <= 380:
        return "yearly"
    return "irregular"


def parse_date_value(value: object) -> datetime | None:
    """Parses an extracted date/datetime field's loosely-typed `.value`
    (always a string from A3's JSON output — ISO-8601 date or datetime)
    into a real `datetime`. Returns `None` (never raises, never guesses a
    fallback date) if `value` is not a parseable ISO-8601 string — a
    strategy that needs this field to build a node treats `None` the same
    as "field not extracted"."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


__all__ = [
    "as_float",
    "as_str",
    "cadence_from_period",
    "field_by_name",
    "new_edge_id",
    "new_node_id",
    "parse_date_value",
    "provenance_for",
    "slugify",
]

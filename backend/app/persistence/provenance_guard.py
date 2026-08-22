"""The provenance write guard — safety invariant #3, E1's single most
important defence (PHASES.md Phase 1 work item 2).

`validate_provenance` is called by `FirestoreGraphStore` before *any*
mutation reaches the network — a rejected write never partially lands.
Deliberately duck-types its input (`GraphWriter.write_node` accepts
`object` per the frozen contract) rather than requiring a
`contracts.graph_types` dataclass instance, so the guard cannot be
bypassed by handing it something structurally node-shaped but not
literally one of the 16 registered types.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from contracts.errors import ProvenanceMissing
from contracts.graph_types import Derivation

_MISSING: Any = object()
"""Sentinel distinguishing 'attribute absent' from 'attribute present and
explicitly None' — a legitimate AMBIGUOUS-derivation provenance has
`source_ref is None` on purpose (spec §5.6)."""

_REQUIRED_ALWAYS = ("derivation", "confidence", "deriving_agent", "created_at")
"""Provenance fields that may never be missing or None, regardless of
derivation (contracts.errors.ProvenanceMissing's own docstring)."""


def validate_provenance(subject: object) -> None:
    """Raises `contracts.errors.ProvenanceMissing` if `subject.provenance`
    is absent or structurally incomplete.

    Every write path in `app.persistence` / `app.graph` calls this before
    any Firestore mutation — this is safety invariant #3 made structural,
    not a convention callers are trusted to honour.
    """
    provenance = getattr(subject, "provenance", _MISSING)
    if provenance is _MISSING or provenance is None:
        raise ProvenanceMissing(missing_fields=("provenance",))

    missing: list[str] = [
        field_name for field_name in _REQUIRED_ALWAYS if getattr(provenance, field_name, None) is None
    ]

    derivation = getattr(provenance, "derivation", None)
    source_ref = getattr(provenance, "source_ref", _MISSING)
    if source_ref is _MISSING:
        missing.append("source_ref")
    elif source_ref is None and derivation != Derivation.AMBIGUOUS:
        # None is only a valid source_ref for AMBIGUOUS-with-no-single-source
        # (spec §5.6) — anything else with no source_ref is incomplete.
        missing.append("source_ref")

    if missing:
        raise ProvenanceMissing(missing_fields=tuple(missing))


def subject_from_raw_document(doc_id: str, raw: dict[str, Any] | None) -> object:
    """Builds a duck-typed stand-in object from a *raw, undecoded*
    Firestore document dict, suitable for `validate_provenance`, without
    requiring the document to successfully decode into a typed
    `contracts.graph_types` dataclass first.

    This is what lets `FirestoreGraphReader.unexplained` and
    `FirestoreGraphIntegrityChecker` find and report structurally
    corrupted documents (e.g. `{"provenance": None}`, or a document
    missing the `provenance` key entirely) as violations, instead of
    crashing on `decode_node`/`decode_edge` before the provenance check
    ever runs — catching exactly that corruption is the entire point of
    both callers.
    """
    if raw is None:
        return SimpleNamespace(id=doc_id, provenance=None)
    if "provenance" not in raw:
        return SimpleNamespace(id=doc_id)
    provenance_raw = raw["provenance"]
    if not isinstance(provenance_raw, dict):
        # None, or some other malformed shape — validate_provenance
        # treats anything that isn't a provenance-shaped object as missing.
        return SimpleNamespace(id=doc_id, provenance=provenance_raw)
    return SimpleNamespace(id=doc_id, provenance=SimpleNamespace(**provenance_raw))

"""Firestore composite index definitions and migration entrypoint
(`docs/adr/001-firestore-edge-layout.md`).

ADR-001 calls for composite indexes on the flat top-level `edges`
collection: `(from_id, edge_type)` and `(to_id, edge_type)`, supporting
`neighbours()` and every other single-hop traversal in both directions
without a full collection scan.

**This module declares the indexes as data and can apply them against a
real Firestore project via the Admin API — it does not run that apply step
automatically, and it is not run as part of the Phase 1 test suite.**
Real GCP billing is not active yet (`docs/DEBT.md` DEBT-001); this repo's
Phase 1 work runs entirely against the Firestore emulator, which:

- accepts these composite-field equality queries (`from_id ==`, `edge_type
  ==`) without requiring the index to exist at all — the emulator does not
  enforce Firestore's production index requirements, so `edges_from` /
  `edges_to` (`app/persistence/firestore_store.py`) are exercised and
  proven correct in Phase 1's tests regardless; and
- has no Admin API index-management surface to apply these against in the
  first place.

`apply_indexes` is therefore real, complete code — never a stub — but it
is only ever invoked against a real GCP project, which does not exist yet
for this repo. See this phase's final report for the corresponding
`docs/DEBT.md` candidate: applying these indexes is Phase-2-or-later work,
once a real GCP project exists (Phase 2 is where this repo first deploys
to real Cloud Run per PHASES.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore_admin_v1


@dataclass(frozen=True, slots=True)
class CompositeIndexSpec:
    """One composite index definition: an ascending-field index on a
    collection group, matching the shape `firestore_admin_v1.Index`
    expects but without requiring a live client to construct."""

    collection_group: str
    field_names: tuple[str, ...]
    """Order matters — Firestore composite indexes are ordered."""


EDGE_FROM_ID_EDGE_TYPE_INDEX = CompositeIndexSpec(
    collection_group="edges",
    field_names=("from_id", "edge_type"),
)
"""Backs `FirestoreGraphStore.edges_from` — outgoing single-hop traversal
(`neighbours`, `load`, `history`, `expected_but_absent`, `conflicts`,
`decisions_touching`, and the `path`/`blast_radius` adjacency build)."""

EDGE_TO_ID_EDGE_TYPE_INDEX = CompositeIndexSpec(
    collection_group="edges",
    field_names=("to_id", "edge_type"),
)
"""Backs `FirestoreGraphStore.edges_to` — incoming single-hop traversal
(`neighbours`, `series`, `concession_ledger`, `unverified`,
`effort_evidence`, `conflicts`, `decisions_touching`)."""

ALL_COMPOSITE_INDEXES: tuple[CompositeIndexSpec, ...] = (
    EDGE_FROM_ID_EDGE_TYPE_INDEX,
    EDGE_TO_ID_EDGE_TYPE_INDEX,
)


def _to_admin_index(spec: CompositeIndexSpec) -> firestore_admin_v1.Index:
    return firestore_admin_v1.Index(
        query_scope=firestore_admin_v1.Index.QueryScope.COLLECTION,
        fields=[
            firestore_admin_v1.Index.IndexField(
                field_path=field_name,
                order=firestore_admin_v1.Index.IndexField.Order.ASCENDING,
            )
            for field_name in spec.field_names
        ],
    )


def apply_indexes(
    admin_client: firestore_admin_v1.FirestoreAdminClient,
    *,
    project_id: str,
    database: str = "(default)",
) -> tuple[str, ...]:
    """Creates every index in `ALL_COMPOSITE_INDEXES` against a real
    Firestore project via the Admin API. Idempotent in effect (Firestore
    rejects a duplicate index definition with `ALREADY_EXISTS`, which this
    function treats as success, not failure) but each `create_index` call
    still reaches the network — never call this against the emulator (no
    Admin API surface there) or without `project_id` pointing at a real,
    billed project.

    Returns:
        One long-running-operation name per index actually submitted.
    """
    parent = f"projects/{project_id}/databases/{database}/collectionGroups/{{collection_group}}"
    operation_names: list[str] = []
    for spec in ALL_COMPOSITE_INDEXES:
        request = firestore_admin_v1.CreateIndexRequest(
            parent=parent.format(collection_group=spec.collection_group),
            index=_to_admin_index(spec),
        )
        try:
            operation = admin_client.create_index(request=request)
        except AlreadyExists:
            continue
        operation_names.append(operation.operation.name)
    return tuple(operation_names)

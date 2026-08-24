"""Shared `ObligationStatus` lifecycle groupings used across `app.graph`.

Factored out so `FirestoreObligationRepository.open_obligations_for` and
`FirestoreGraphReader.load` (Phase 4 hardening — PHASES.md Phase 4, E1 work
item 2) agree on exactly which statuses count as "closed" rather than each
defining its own copy of the same three-value tuple (gharos-standards
skill, rule 3: no magic values duplicated across call sites).
"""

from __future__ import annotations

from contracts.graph_types import ObligationStatus

CLOSED_OBLIGATION_STATUSES: tuple[ObligationStatus, ...] = (
    ObligationStatus.COMPLETED,
    ObligationStatus.DROPPED,
    ObligationStatus.SUPERSEDED,
)
"""An OBLIGATION in one of these statuses is no longer live work: COMPLETED
is done, DROPPED was explicitly abandoned, SUPERSEDED was replaced by a
newer version (spec §5.2's status sequence: derived -> assigned -> prepared
-> in-progress -> completed | dropped | superseded). Anything else
(DERIVED, ASSIGNED, PREPARED, IN_PROGRESS) is still open and should count
toward a person's current load, temporal footprint, and capability
exposure."""

__all__ = ["CLOSED_OBLIGATION_STATUSES"]

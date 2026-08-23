"""`DocumentTypeRegistry` — the Document-Type Registry as a strategy
pattern (spec §5.4, PHASES.md §2.2, ADR-008).

Owns the open `type_id -> (DocumentTypeSpec, ExtractionStrategy)` mapping.
E3 (this phase) populates it with all fourteen `DocumentTypeSpec` data
entries from `document_type_specs.py`; E2 (next round) registers a
concrete `ExtractionStrategy` per `type_id`. Adding a fifteenth document
type later means adding one `DocumentTypeSpec` + one `ExtractionStrategy`
and calling `register()` once more — nothing here branches on `type_id`,
so the pipeline this registry serves (A2 route -> A3 extract off
`DocumentTypeSpec.field_schema` -> resolved strategy's `map_to_graph()`)
never grows an `if/elif` (gharos-standards: Strategy pattern, explicitly
named as the alternative to that).

Deliberately holds no module-level singleton state (gharos-standards: "no
module-level singletons holding I/O") — a fresh `DocumentTypeRegistry()`
is cheap to construct, so every test gets its own, and the composition
root builds exactly one for the running process.
"""

from __future__ import annotations

from contracts.errors import RegistryGap
from contracts.graph_types import DocumentTypeSpec, ExtractionStrategy


class DuplicateRegistration(ValueError):
    """Raised by `register()` when `type_id` already has a registered
    entry. A silent overwrite here would let a later, possibly-buggy
    registration quietly replace an earlier, correct one with no signal —
    exactly the kind of silent failure gharos-standards rules out
    elsewhere (e.g. "never silently overwrite" for verification
    documents, spec §5.5). Re-registering the same `type_id` is always a
    caller bug (double import-time registration, a copy-paste in
    composition-root wiring), never a legitimate runtime path, so this is
    a hard error, not a warning."""

    def __init__(self, *, type_id: str) -> None:
        self.type_id = type_id
        super().__init__(f"document type '{type_id}' is already registered")


class TypeIdMismatch(ValueError):
    """Raised by `register()` when the `type_id` argument does not match
    `spec.type_id` — catches a copy-paste error at registration time
    rather than letting `resolve()` silently return a spec whose own
    `type_id` field disagrees with the key it was filed under."""

    def __init__(self, *, registered_as: str, spec_type_id: str) -> None:
        self.registered_as = registered_as
        self.spec_type_id = spec_type_id
        super().__init__(f"registered under '{registered_as}' but spec.type_id is '{spec_type_id}'")


class DocumentTypeRegistry:
    """Dependency-injected, per-instance registry — see module docstring.

    Example (E3's Phase 3 wiring — data only, no strategies yet):

        registry = DocumentTypeRegistry()
        # E2, Phase 3 second half:
        # registry.register(document_type_ids.RECEIPT, receipt_spec, ReceiptExtractionStrategy())

    Example (A2 Intake Router, E2, consuming this registry):

        try:
            spec, strategy = registry.resolve(classified_type_id)
        except RegistryGap as gap:
            record_registry_gap(gap_log, gap, channel=channel)
            # generic extraction + human triage (spec §5.4.3 rule 4)
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[DocumentTypeSpec, ExtractionStrategy]] = {}

    def register(self, type_id: str, spec: DocumentTypeSpec, strategy: ExtractionStrategy) -> None:
        """Registers one document type's spec and extraction strategy.

        Args:
            type_id: canonical snake_case identifier — must match
                `spec.type_id` exactly (see `document_type_ids.py` for the
                fourteen canonical strings).
            spec: the declarative `DocumentTypeSpec` (detection signals,
                field schema, target nodes/edges, downstream subsystems,
                verification duties).
            strategy: the `ExtractionStrategy` turning this type's
                extracted fields into graph writes (E2-owned).

        Raises:
            TypeIdMismatch: `type_id != spec.type_id`.
            DuplicateRegistration: `type_id` is already registered.
        """
        if type_id != spec.type_id:
            raise TypeIdMismatch(registered_as=type_id, spec_type_id=spec.type_id)
        if type_id in self._entries:
            raise DuplicateRegistration(type_id=type_id)
        self._entries[type_id] = (spec, strategy)

    def resolve(self, type_id: str) -> tuple[DocumentTypeSpec, ExtractionStrategy]:
        """Looks up a registered type's spec and strategy.

        Raises rather than returning `None` on a miss: spec §5.4.3 rule 4
        ("unknown type -> generic extraction + human triage... log it as
        a registry gap") describes a miss as an actual failure mode with
        a mandatory response, not a value a caller might reasonably
        ignore — a typed exception makes "the caller must decide what to
        do" structural rather than relying on every call site to check
        for `None`. `contracts.errors.RegistryGap` already exists for
        exactly this (CTO-frozen); callers should catch it and pass it to
        `registry_gap_log.record_registry_gap()`.

        Args:
            type_id: the classified document type (A2 Intake Router's
                output).

        Returns:
            `(DocumentTypeSpec, ExtractionStrategy)` for `type_id`.

        Raises:
            RegistryGap: `type_id` has no registered entry.
        """
        entry = self._entries.get(type_id)
        if entry is None:
            raise RegistryGap(
                detection_summary=f"no registered DocumentTypeSpec/ExtractionStrategy for '{type_id}'"
            )
        return entry

    def known_type_ids(self) -> tuple[str, ...]:
        """All currently-registered `type_id`s, sorted for deterministic
        output. A2 Intake Router (E2) uses this to know the full candidate
        set for classification (spec §5.4.3 rule 1: classify before
        extraction) without importing `document_type_specs.py` or
        `document_type_ids.py` directly."""
        return tuple(sorted(self._entries))

    def has_type(self, type_id: str) -> bool:
        """`True` if `type_id` is registered — lets a caller check without
        catching `RegistryGap` for the common "do I even attempt this"
        pre-check (e.g. spec §5.4.3 rule 3's multi-type-match path, which
        needs to try two candidate schemas without raising on either)."""
        return type_id in self._entries

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["DocumentTypeRegistry", "DuplicateRegistration", "TypeIdMismatch"]

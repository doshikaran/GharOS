"""GharOS — frozen graph type contracts.

Owned exclusively by the CTO (PHASES.md §1). This module defines every node
and edge type in the Household Knowledge Graph (spec §5.2, §5.3) as frozen,
immutable dataclasses, plus the provenance discipline (spec §5.6) that every
single one of them carries.

**No Firestore, FastAPI, or any other infrastructure import belongs in this
file.** It must remain importable in total isolation — that isolation is
what lets `backend/app/graph/` (E1), `backend/app/agents/` (E2),
`backend/app/tools/` (E3) and `frontend/` (E4) all build against the exact
same shapes without depending on each other's infrastructure choices
(PHASES.md §2.2 — hexagonal / ports-and-adapters).

Changing this file is a CTO-only action (PHASES.md Appendix D, rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, NewType, Protocol

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

NodeId = NewType("NodeId", str)
EdgeId = NewType("EdgeId", str)
AgentId = NewType("AgentId", str)
"""One of the agent identifiers from spec §15, e.g. 'A12' (Implication Agent)."""


# ---------------------------------------------------------------------------
# Provenance — the single most important discipline in the system (spec §5.6)
# ---------------------------------------------------------------------------


class Derivation(str, Enum):
    """How a node or edge came to exist.

    - EXTRACTED: literally present in the source, openable at a specific region.
    - INFERRED: reasoned from structure and context; usually right, worth checking.
    - AMBIGUOUS: evidence points more than one way, and the graph says so.
    """

    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Pointer to the SOURCE_DOCUMENT and the region within it that produced
    a node or edge. Every extracted or inferred field carries one — spec §5.4.3
    rule 5 makes this non-negotiable across every document type.
    """

    source_document_id: NodeId
    region: str
    """Free-form region locator: a bounding box, a line range, a character
    span, an audio timestamp range — whatever the source medium supports.
    Never empty for an EXTRACTED or INFERRED item."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """Mixin-by-composition every node and edge carries (spec §5.6).

    A repository write missing any required field here must be REJECTED,
    not merely logged — this is E1's Phase 1 top-priority defence
    (PHASES.md Phase 1, work item 2) and safety invariant #3.
    """

    derivation: Derivation
    source_ref: SourceRef | None
    """None only for AMBIGUOUS-with-no-single-source cases (e.g. a mined
    PATTERN with multiple contributing OUTCOMEs) — validated at the
    repository layer per node/edge type, not globally permitted."""
    confidence: float
    """0.0-1.0. Below the action-tier's confidence floor, the arbiter
    downgrades tier, escalates, or discards — never proceeds silently
    (spec §19.2, safety invariant #4)."""
    deriving_agent: AgentId
    created_at: datetime
    superseded_at: datetime | None = None
    """Set, never overwritten, when a later write supersedes this one
    (PHASES.md Phase 1, work item 3 — versioning, not in-place mutation)."""

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")
        if self.derivation in (Derivation.EXTRACTED, Derivation.INFERRED) and self.source_ref is None:
            raise ValueError(f"{self.derivation.value} provenance requires a source_ref")


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class PersonRole(str, Enum):
    ADULT = "adult"
    CHILD = "child"
    ELDER = "elder"
    STAFF = "staff"
    EXTENDED = "extended"


class ConstraintKind(str, Enum):
    DIETARY = "dietary"
    MEDICAL = "medical"
    SCHEDULE = "schedule"
    FINANCIAL = "financial"
    RELIGIOUS = "religious"
    LEGAL = "legal"
    CUSTODY = "custody"
    MOBILITY = "mobility"


class ConstraintSeverity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class ObligationStatus(str, Enum):
    DERIVED = "derived"
    ASSIGNED = "assigned"
    PREPARED = "prepared"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    DROPPED = "dropped"
    SUPERSEDED = "superseded"


class ObligationDerivation(str, Enum):
    """Distinct from Derivation — this is spec §5.2's OBLIGATION-specific
    'stated vs implied' tag, the flagship distinction of the Consequence
    Engine (spec §7.3 Stage 2)."""

    STATED = "stated"
    IMPLIED = "implied"


class LedgerEventKind(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    DUE = "due"
    MANDATE_CREATED = "mandate_created"
    MANDATE_CANCELLED = "mandate_cancelled"
    PRICE_CHANGE = "price_change"
    REFUND = "refund"
    SALARY = "salary"
    ADVANCE = "advance"


class LiteracyMode(str, Enum):
    VOICE_ONLY = "voice_only"
    TEXT_CAPABLE = "text_capable"
    BOTH = "both"


class DecisionStatus(str, Enum):
    OPEN = "open"
    BRIEFED = "briefed"
    RESOLVED = "resolved"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    """Expiry escalates; it never auto-approves (spec §18.2)."""


# ---------------------------------------------------------------------------
# Node types (spec §5.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """Per-PERSON language profile (spec §14.3) — language is a graph
    property, not a global setting."""

    primary_language: str
    languages_understood: tuple[str, ...]
    script_preference: str
    code_mixing_profile: str | None
    formality_preference: str | None
    literacy_mode: LiteracyMode


@dataclass(frozen=True, slots=True)
class Person:
    id: NodeId
    provenance: Provenance
    display_name: str
    aliases: tuple[str, ...]
    role: PersonRole
    can_drive: bool
    can_sign: bool
    has_bank_access: bool
    has_medical_proxy: bool
    contact_channels: tuple[str, ...]
    language_profile: LanguageProfile
    voiceprint_ref: str | None = None
    pronunciation_hints: str | None = None


@dataclass(frozen=True, slots=True)
class Constraint:
    id: NodeId
    provenance: Provenance
    kind: ConstraintKind
    severity: ConstraintSeverity
    validity_start: datetime | None
    validity_end: datetime | None
    structured: dict[str, str]
    """Machine-checkable form, e.g. {'allergen': 'nut'}."""
    original_text: str
    """The natural-language original — never discarded (spec §14.3 rule 5)."""


@dataclass(frozen=True, slots=True)
class Obligation:
    id: NodeId
    provenance: Provenance
    title: str
    obligation_type: str
    due_at: datetime | None
    must_start_by: datetime | None
    """Computed backwards through dependencies and availability (spec §7.3 Stage 4)."""
    effort_estimate_minutes: int | None
    status: ObligationStatus
    stated_or_implied: ObligationDerivation


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    id: NodeId
    provenance: Provenance
    kind: LedgerEventKind
    amount: float
    currency: str
    occurred_at: datetime
    counterparty_raw: str
    """The raw merchant/VPA string as seen — entity resolution confidence on
    this is frequently low (spec §5.4.2, UPI SMS note) and must not on its
    own drive a cancellation recommendation."""


@dataclass(frozen=True, slots=True)
class RecurringCommitment:
    id: NodeId
    provenance: Provenance
    label: str
    counterparty: str
    amount: float
    cadence: str
    price_history: tuple[tuple[datetime, float], ...]
    last_used_at: datetime | None
    status: Literal["active", "paused", "cancelled"]


@dataclass(frozen=True, slots=True)
class Vendor:
    id: NodeId
    provenance: Provenance
    category: str
    contacts: tuple[str, ...]
    reliability_score: float | None
    response_latency_hours: float | None


@dataclass(frozen=True, slots=True)
class Provider:
    id: NodeId
    provenance: Provenance
    name: str
    category: str
    rating: float | None
    distance_km: float | None
    availability_notes: str | None
    price_band: str | None
    specialisations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Decision:
    id: NodeId
    provenance: Provenance
    question: str
    trigger: str
    status: DecisionStatus
    resolution_summary: str | None
    rationale: str | None
    """Permanent record. Never pruned — spec §5.2, PHASES.md Phase 14."""


@dataclass(frozen=True, slots=True)
class Branch:
    id: NodeId
    provenance: Provenance
    decision_id: NodeId
    label: str
    projected_impacts: dict[str, str]
    grounding_refs: tuple[str, ...]
    critiques: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CouncilPosition:
    """What makes the council auditable rather than mystical (spec §5.2)."""

    id: NodeId
    provenance: Provenance
    decision_id: NodeId
    held_by_agent: AgentId
    stance: Literal["supports", "opposes", "neutral"]
    branch_id: NodeId | None
    reasoning: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Outcome:
    id: NodeId
    provenance: Provenance
    predicted: str
    actual: str
    variance: float | None
    attribution_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: NodeId
    provenance: Provenance
    channel: str
    raw_payload_ref: str
    document_type: str | None
    """Set by the Intake Router (A2) once classified against the
    Document-Type Registry (spec §5.4). None while pending classification."""
    ingested_at: datetime
    original_language: str | None


@dataclass(frozen=True, slots=True)
class ActionRecord:
    id: NodeId
    provenance: Provenance
    action_type: str
    executed_at: datetime
    approved_by: NodeId | None
    """PERSON id, if this action required approval. None for R0/R1 actions."""


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    id: NodeId
    provenance: Provenance
    proposed_action_summary: str
    evidence_bundle: dict[str, str]
    risk_tier: str
    """R0-R4 — see contracts/actions.py:RiskTier. Kept as str here to avoid
    a circular import; the repository layer validates against RiskTier."""
    confidence: float
    consequence_if_wrong: str
    status: ApprovalStatus
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PurchaseItem:
    """The finest-grained evidence node in the system (spec §5.2, §5.7)."""

    id: NodeId
    provenance: Provenance
    ledger_event_id: NodeId
    description: str
    normalized_category: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float


@dataclass(frozen=True, slots=True)
class Pattern:
    id: NodeId
    provenance: Provenance
    description: str
    support_count: int
    contributing_outcome_ids: tuple[NodeId, ...]


# ---------------------------------------------------------------------------
# Edge types (spec §5.3)
# ---------------------------------------------------------------------------


class EdgeType(str, Enum):
    STATES = "states"
    IMPLIES = "implies"
    OWNED_BY = "owned_by"
    BENEFITS = "benefits"
    CONFLICTS_WITH = "conflicts_with"
    VIOLATES = "violates"
    DEPENDS_ON = "depends_on"
    SUPERSEDES = "supersedes"
    COMPLETES_INTO = "completes_into"
    BELONGS_TO = "belongs_to"
    OWED_TO = "owed_to"
    PAID_FOR = "paid_for"
    CONTAINS = "contains"
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    GROUNDED_IN = "grounded_in"
    RESOLVED_AS = "resolved_as"
    CONCEDED_BY = "conceded_by"
    PREDICTED_BY = "predicted_by"
    CONSTRAINS = "constrains"
    BOOKED_WITH = "booked_with"
    LEARNED_FROM = "learned_from"
    LINE_ITEM_OF = "line_item_of"
    DISCHARGES = "discharges"
    VERIFIES = "verifies"
    CONTRADICTS = "contradicts"
    ABSENT_FROM = "absent_from"
    SUBSTITUTES = "substitutes"
    EVIDENCES_EFFORT = "evidences_effort"
    COVERS = "covers"
    """OBLIGATION -> PURCHASE_ITEM. A warranty/purchase-protection claim-or-
    lose OBLIGATION back to the originating receipt's PURCHASE_ITEM (spec
    §5.4.2 WARRANTY: "links back to the originating RECEIPT's PURCHASE_ITEM
    — this is why receipt line-item extraction matters months later").
    Added Phase 3 (ADR-009) — spec named this relationship explicitly but
    the original 29-edge table never gave it its own edge type."""
    ACTS_ON = "acts_on"
    """ACTION_RECORD -> {OBLIGATION | LEDGER_EVENT | VENDOR | PROVIDER |
    RECURRING_COMMITMENT}. The "what" half of spec §5.2's ACTION_RECORD
    description ("what the system did, when, under whose approval") — an
    ActionRecord with no ACTS_ON edge names an action_type string but
    points at nothing, making "show every action ever taken on this
    obligation" unanswerable by traversal. Added Phase 5 (ADR-012)."""
    AUTHORIZES = "authorizes"
    """APPROVAL_REQUEST -> ACTION_RECORD. The specific approval that
    authorized this specific executed action — the "under whose approval"
    half of ACTION_RECORD's description, at request granularity (not just
    the approving person). Added Phase 5 (ADR-012), repays DEBT-002."""
    APPROVED_BY = "approved_by"
    """APPROVAL_REQUEST -> PERSON. The graph-traversal-visible form of who
    approved a request — deliberately kept alongside
    `ActionRecord.approved_by`'s existing scalar NodeId field rather than
    replacing it (that field is a fast, already-relied-upon denormalized
    convenience; this edge is what makes "every approval Priya has ever
    granted" answerable by `GraphReader.neighbours`, consistent with every
    other relationship in this graph being edge-first). Added Phase 5
    (ADR-012), repays DEBT-002."""


@dataclass(frozen=True, slots=True)
class Edge:
    """A single typed, directional edge. `from_id`/`to_id` are NodeIds;
    the repository layer (E1, per PHASES.md Phase 1) is responsible for
    validating that a given (edge_type, from_node_type, to_node_type)
    triple is one of the pairs listed in spec §5.3 — this contract defines
    the shape, not the validation table, to avoid coupling this module to
    every node type's runtime class.
    """

    id: EdgeId
    provenance: Provenance
    edge_type: EdgeType
    from_id: NodeId
    to_id: NodeId
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Document-Type Registry entry shape (spec §5.4.1) — the CONTRACT a strategy
# must satisfy; E3 owns the registry and its concrete strategies
# (backend/app/adapters/), never this shared shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldSchema:
    name: str
    field_type: str
    required: bool
    confidence_floor: float


@dataclass(frozen=True, slots=True)
class DocumentTypeSpec:
    """One entry in the open Document-Type Registry (spec §5.4). Adding a
    document type means adding one of these plus an `ExtractionStrategy`
    (below) — never modifying the extraction pipeline (strategy pattern,
    PHASES.md §2.2). The registry (owned by E3, `backend/app/adapters/`)
    maps `type_id` to a `(DocumentTypeSpec, ExtractionStrategy)` pair; the
    pipeline (A2 route -> A3 extract, schema-driven off `field_schema` ->
    `ExtractionStrategy.map_to_graph`) never branches on `type_id` itself.
    """

    type_id: str
    detection_signals: tuple[str, ...]
    field_schema: tuple[FieldSchema, ...]
    target_node_types: tuple[str, ...]
    target_edge_types: tuple[EdgeType, ...]
    downstream_subsystems: tuple[str, ...]
    verification_duties: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractedField:
    """One field's extracted value, with the provenance that lets it become
    part of a node's own `Provenance` once written — extraction confidence
    and source region are per-field, not per-document (spec §5.4.1: "field-
    level confidence and source-region pointers")."""

    name: str
    value: object
    """Loosely typed on purpose — a `FieldSchema.field_type` of "string",
    "number", "date", or "list" all flow through here; the concrete
    `ExtractionStrategy` for a given type knows how to interpret its own
    schema's field types, and mypy --strict on `ExtractionStrategy`
    implementations is where real type safety per type actually lives."""
    confidence: float
    source_region: str
    """Pairs with `SourceRef.region` — never empty for a field derived from
    the document itself (spec §5.4.3 rule 5: every extracted field carries
    a source-region pointer, no exceptions)."""
    derivation: Derivation


@dataclass(frozen=True, slots=True)
class GraphMappingResult:
    """What one `ExtractionStrategy.map_to_graph()` call produces: the
    concrete graph writes this document implies, plus any verification
    findings — never applied directly by the strategy itself (strategies
    return data; only `GraphWriter`, via the writer-agent pipeline, ever
    touches Firestore — Layer 3/Layer 5 separation, spec §6.2)."""

    nodes: tuple[object, ...]
    """Concrete `contracts.graph_types` node instances (frozen dataclasses
    from this module) ready to write — each already carrying full
    `Provenance`."""
    edges: tuple[Edge, ...]
    verification_findings: tuple[str, ...] = ()
    """Human-readable notes for verification-document types (spec §5.5) —
    e.g. an `absent_from` signal or a `contradicts` discrepancy this
    mapping detected. Empty for non-verification types."""
    registry_gap: bool = False
    """True only for the generic fallback strategy (spec §5.4.3 rule 4:
    unknown type -> generic extraction + human triage + logged registry
    gap) — never true for a real registered type's own strategy."""


class ExtractionStrategy(Protocol):
    """The Strategy-pattern interface every document type's edge-mapping
    logic implements (PHASES.md §2.2, spec §5.4). One concrete
    implementation per `DocumentTypeSpec.type_id`, owned by E2
    (`backend/app/agents/consequence/` or a type-specific module — E2's
    call), registered into E3's registry (`backend/app/adapters/`). Adding
    a new document type means writing one new class satisfying this
    Protocol and registering it — the shared pipeline (A2 route -> A3
    extract -> this call -> GraphWriter) never changes.
    """

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        """Interprets one document's extracted fields into graph writes.

        Args:
            source_document_id: the SOURCE_DOCUMENT node this extraction
                came from — every produced node's `Provenance.source_ref`
                traces back to it.
            extracted_fields: A3's (or A3b's) output for this document,
                shaped by this type's own `DocumentTypeSpec.field_schema`.
            deriving_agent: which agent is calling this strategy (for
                `Provenance.deriving_agent` on every node/edge produced).

        Returns:
            The nodes and edges this document implies, plus any
            verification findings.
        """
        ...

"""GharOS — frozen ingestion-connector & end-to-end-wire contracts (Phase 14.5).

Owned exclusively by the CTO. This module is the cross-role shape set for
the *triggerable* ingestion path: a household member says "scan my Gmail
and Outlook" (by text or by voice), and a real orchestrator reads the last
24 hours through official OAuth APIs, plus a file / Drive-picker upload
path, and drives every item through the Phase 3 stages to committed graph
nodes (DEBT-009's repayment).

**Why a new module and not `contracts/events.py`.** `events.py` is the
asynchronous Pub/Sub signal envelope (`InboundEnvelope`) — one topic
shape every channel publishes onto. Phase 14.5's `POST /ingest` is a
different concern: a synchronous, caller-triggered *orchestration run*
with a first-class, honest per-document outcome record. It shares no
structure with `InboundEnvelope`; giving it its own module keeps the
whole ingestion-connector surface reviewable in one place, the way
`actions.py` / `tools.py` each own one concern.

**No Firestore, FastAPI, ADK, `google-*` SDK, or any other infrastructure
import belongs here.** Standard library only — this module must stay
importable in total isolation (see `contracts/__init__.py`). Concrete
connectors, the orchestrator, and the OAuth routes live in
`backend/app/` (E3); the credential / dedupe stores live in
`backend/app/persistence/` (E1).

Result-vs-exception policy (ADR-002): a *run's* outcome — including a
whole connector failing mid-run — is reported as data on
`IngestionRunResult`, never raised (spec §19.3: "failures reported, not
hidden"). Only a caller-setup precondition that makes a run impossible
(no connected account, an insufficient scope grant) is raised, as one of
the typed `IngestionError` subclasses in `contracts/errors.py`.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

# ---------------------------------------------------------------------------
# Raw intake payload — the channel-agnostic envelope a SourceConnector
# produces. RE-HOMED here from `backend/app/adapters/ingestion.py` in
# Phase 14.5: it is no longer an E3-internal seam ("no other role imports
# this module directly") — the frozen `SourceConnector` protocol below
# returns it and E2's orchestrator consumes it, so it is now a genuine
# cross-role shape and belongs in `contracts/`. `backend/app/adapters/
# ingestion.py` re-exports this name unchanged for its existing callers
# (the four Phase 3 adapters); `resolve_raw_payload_ref` and
# `STORAGE_REF_HEADER` stay in that adapter module — they are logic, not
# shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawIntakePayload:
    """The channel-agnostic envelope a `SourceConnector` (Gmail, Outlook,
    Drive picker) or the `POST /ingest` multipart handler assembles before
    the matching `app.adapters` normalizer's `normalize()` runs.

    Deliberately loose (`text` / `binary` both optional, `headers`
    untyped): "ingestion fragility is an adapter problem, not a
    core-architecture problem" (spec §17). Each concrete adapter imposes
    the real per-channel structure on top of this by validating the
    headers / content shape it actually requires.

    Two `headers` keys are named by constants in this module and carry
    contractual meaning for the Phase 14.5 wire:

    - `STORAGE_REF_HEADER` (`"storage_ref"`, defined in
      `app.adapters.ingestion`) — set when the raw bytes were already
      durably stored, so the normalizer passes the ref through instead of
      deriving a content-hash fallback.
    - `EXTERNAL_IDENTITY_HEADER` (`"external_identity"`, below) — the
      provider's immutable per-item id (Gmail / Microsoft Graph message
      id; Drive `fileId:headRevisionId`). A `SourceConnector` MUST set it;
      the `direct_upload` path leaves it unset and dedupe falls back to
      hashing the raw bytes. It is the strongest input to
      `compute_content_hash`.
    """

    text: str | None
    binary: bytes | None
    media_type: str
    headers: dict[str, str] = field(default_factory=dict)
    received_at: datetime | None = None


EXTERNAL_IDENTITY_HEADER = "external_identity"
"""`RawIntakePayload.headers` key: the provider's immutable, stable,
per-item identifier. Gmail / Microsoft Graph: the message `id`. Google
Drive picker: `f"{file_id}:{head_revision_id}"`. Unset for
`direct_upload`. Read by the orchestrator as the `external_identity`
argument to `compute_content_hash` — named once here so every connector
and the dedupe check agree on the key."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IngestionSourceKind(str, Enum):
    """Which connector / upload path an ingested item came in through.

    Deliberately short and closed — Phase 14.5's scope is exactly these
    four (PHASES.md Phase 14.5: "any local-filesystem, Apple Photos,
    iMessage, or WhatsApp read" is explicitly out of scope; Google Photos
    is Picker-only). A future native desktop companion would add members
    here, not reshape the contract."""

    GMAIL = "gmail"
    OUTLOOK = "outlook"
    DRIVE_PICKER = "drive_picker"
    DIRECT_UPLOAD = "direct_upload"


SCANNING_SOURCE_KINDS: frozenset[IngestionSourceKind] = frozenset(
    {IngestionSourceKind.GMAIL, IngestionSourceKind.OUTLOOK}
)
"""The source kinds a `SourceConnector.fetch_since` window-scan applies to
— the two that read a time-bounded slice of a remote mailbox through an
OAuth token. `DRIVE_PICKER` and `DIRECT_UPLOAD` deliver explicitly chosen
items as `IngestionRequest.inline_payloads`, not a scan. Named here so
`IngestionRequest.__post_init__` and the orchestrator agree on which
kinds require a `window` + `principal`."""


class OAuthProvider(str, Enum):
    """The OAuth authorization server a stored credential belongs to —
    distinct from `IngestionSourceKind` because one Google grant
    (`gmail.readonly` + `drive.file`) can back both the `GMAIL` and
    `DRIVE_PICKER` sources."""

    GOOGLE = "google"
    MICROSOFT = "microsoft"


class DocumentIngestStatus(str, Enum):
    """The honest per-document outcome of one orchestrator run. Every item
    the wire sees ends on exactly one of these — there is no silent drop
    (Gate 14.5: "a failed extraction is a visible failure, never a silent
    drop")."""

    INGESTED = "ingested"
    """Classified, extracted, entity-resolved, mapped to graph, committed.
    `DocumentIngestOutcome.new_node_ids` is non-empty."""

    DUPLICATE_SKIPPED = "duplicate_skipped"
    """`compute_content_hash` matched a prior `IngestionDedupeStore`
    entry — the same window re-scanned. Nothing written.
    `DocumentIngestOutcome.source_document_id` points at the ORIGINAL
    SOURCE_DOCUMENT node (Gate 14.5: "re-scanning the same 24-hour window
    writes zero new nodes")."""

    EXTRACTION_FAILED = "extraction_failed"
    """A2 classified a known type but A3 / A3b extraction fell below its
    schema's confidence floor, or `map_to_graph` produced nothing usable.
    The SOURCE_DOCUMENT node and the raw payload are retained;
    `detail` carries the reason (spec §15.2 A3 failure clause)."""

    REGISTRY_GAP = "registry_gap"
    """A2 hit a document type not in the Document-Type Registry. The
    generic fallback strategy ran (SOURCE_DOCUMENT written, generic
    extraction retained), the gap is logged, and the item is routed to
    human triage — never discarded (spec §5.4.3 rule 4).
    `GraphMappingResult.registry_gap is True` for this path."""

    ENTITY_RESOLUTION_ESCALATED = "entity_resolution_escalated"
    """A5 could not confidently map a HARD-constraint-bearing mention to a
    single graph node (`contracts.errors.AmbiguousEntity` with
    `hard_constraint_bearing=True`). The wire deliberately did NOT write
    the typed mapping — it escalates with the raw document and its
    reasoning instead (spec §15.2 A5 failure clause; the "knows when not
    to act" rubric point). The SOURCE_DOCUMENT node is retained;
    `detail` names the ambiguous mention and the candidate node ids."""

    ERROR = "error"
    """An unexpected failure at some stage (a raised exception the
    orchestrator caught at its per-document boundary). `detail` carries
    the exception summary. Distinct from the four expected outcomes above
    and from a whole-connector failure (`ConnectorFailure`)."""


# ---------------------------------------------------------------------------
# Content hash — the idempotency key for one ingested document
# ---------------------------------------------------------------------------

INGESTION_CONTENT_HASH_VERSION = "gharos.ingest.v1"
"""Version tag mixed into every `compute_content_hash` digest so the
hashing scheme can evolve without silently colliding old and new hashes
in the `IngestionDedupeStore`."""

_CONTENT_HASH_SEP = b"\x1e"


def compute_content_hash(
    *,
    source_kind: IngestionSourceKind,
    external_identity: str,
    media_type: str,
    raw_bytes: bytes | None,
    text_content: str | None,
) -> str:
    """The per-`SourceDocument` idempotency hash the orchestrator checks
    against `IngestionDedupeStore.seen` before writing anything (ADR-023).

    A pure, deterministic function — defined here, in the frozen contract,
    so all four connectors, the orchestrator's dedupe check, and every
    test compute it identically (the same discipline `contracts.actions`
    `tier_at_least` / `downgrade_tier` follow).

    The digest is `sha256` over, in this fixed order, `\\x1e`-separated:

    1. `INGESTION_CONTENT_HASH_VERSION`
    2. `source_kind.value`
    3. `external_identity` — the provider's immutable per-item id
       (`RawIntakePayload.headers[EXTERNAL_IDENTITY_HEADER]`). Empty
       string for `direct_upload`, which makes items 4-5 the whole
       identity for that path.
    4. `media_type`
    5. `sha256(raw_bytes or b"")` hex — pre-hashed so this input is
       fixed-length regardless of a large PDF / image.
    6. `text_content` after Unicode NFC normalization, or `""` — the
       NORMALIZED text (`NormalizedIntake.text_content`), so a forwarded
       school notice re-forwarded with different quoting boilerplate
       still dedupes.

    Two genuinely different messages never collide; the same message
    fetched twice always matches; a genuinely edited resend (new body,
    or a Drive file's new `headRevisionId`) is correctly treated as new.
    """
    digest = hashlib.sha256()
    digest.update(INGESTION_CONTENT_HASH_VERSION.encode("utf-8"))
    parts: tuple[bytes, ...] = (
        source_kind.value.encode("utf-8"),
        external_identity.encode("utf-8"),
        media_type.encode("utf-8"),
        hashlib.sha256(raw_bytes if raw_bytes is not None else b"").hexdigest().encode("ascii"),
        unicodedata.normalize("NFC", text_content if text_content is not None else "").encode("utf-8"),
    )
    for part in parts:
        digest.update(_CONTENT_HASH_SEP)
        digest.update(part)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The run: request in, honest result out
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    """What a caller hands the one ingestion entry point (`POST /ingest`,
    or the A67 `ingest.scan_mailbox` voice route). One shape covers both
    a connector window-scan and an explicit file / Drive-picker upload —
    "the one `POST /ingest` wire" (Gate 14.5).

    Exactly one orchestrator entry consumes this:
    `run(request: IngestionRequest) -> IngestionRunResult`.
    """

    idempotency_scope: str
    """Caller-chosen scope string for this run (e.g. `"voice-turn:<id>"`,
    `"manual-scan:2026-08-29T14:00Z"`). Distinct from per-document
    `compute_content_hash` dedupe: this scopes an audit record and lets a
    retried identical *run* be recognised, while content-hash dedupe is
    what makes the documents inside it idempotent."""

    triggered_by: str
    """`"voice"`, a PERSON NodeId string, `"manual"`, or a scheduler job
    name — recorded on the run's audit entry and shown in the run view."""

    household_id: str
    """Single-household framing (spec §3.1) — one value for every Phase
    0-15 deployment, mirrors `contracts.events.InboundEnvelope`."""

    sources: tuple[IngestionSourceKind, ...] = ()
    """The scanning connectors to run this pass — a subset of
    `SCANNING_SOURCE_KINDS`. Empty for an upload-only request."""

    window: timedelta | None = None
    """How far back a scanning connector reads (the demo uses 24h).
    Required (and must be positive) when `sources` is non-empty; ignored
    otherwise."""

    principal: str | None = None
    """The connected-account identity (`OAuthCredential.principal`) the
    scanning connectors authenticate as. Required when `sources` is
    non-empty. Single-principal per run in Phase 14.5 (ADR-022)."""

    inline_payloads: tuple[RawIntakePayload, ...] = ()
    """Pre-assembled payloads for `DIRECT_UPLOAD` (multipart parts) and
    `DRIVE_PICKER` (bytes fetched for the user-picked file id). The route
    handler builds these; the orchestrator treats them identically to a
    connector's `fetch_since` output from the normalizer onward."""

    def __post_init__(self) -> None:
        if not self.sources and not self.inline_payloads:
            raise ValueError("IngestionRequest needs at least one of `sources` or `inline_payloads`")
        if self.sources:
            if not set(self.sources).issubset(SCANNING_SOURCE_KINDS):
                allowed = sorted(k.value for k in SCANNING_SOURCE_KINDS)
                raise ValueError(f"`sources` must be a subset of {allowed}")
            if self.window is None or self.window <= timedelta(0):
                raise ValueError("a scanning `sources` request requires a positive `window`")
            if not self.principal:
                raise ValueError("a scanning `sources` request requires a `principal`")


@dataclass(frozen=True, slots=True)
class DocumentIngestOutcome:
    """One document's complete, assertable outcome from one run. Other
    roles serialize this to the frontend run view and assert against it in
    tests — it is a first-class type, never a bare boolean."""

    content_hash: str
    """`compute_content_hash` for this item — the dedupe key, always
    present even on `ERROR` (it is computed before any stage runs)."""

    source: IngestionSourceKind
    status: DocumentIngestStatus

    source_document_id: str | None
    """The SOURCE_DOCUMENT NodeId this item produced (or, for
    `DUPLICATE_SKIPPED`, the pre-existing one). `None` only when the run
    failed before the SOURCE_DOCUMENT node was written."""

    external_ref: str | None
    """`RawIntakePayload.headers[EXTERNAL_IDENTITY_HEADER]` — the Gmail /
    Graph message id or Drive `fileId:rev`, for the run view and the
    dedupe audit trail. `None` for `direct_upload`."""

    classified_type_id: str | None
    """A2's Document-Type Registry classification, if the run reached that
    stage. `None` if it failed earlier; a registry-gap item carries the
    generic fallback marker here, not a real type id."""

    new_node_ids: tuple[str, ...]
    """Graph node ids this document caused to be written this run. Empty
    for every non-`INGESTED` status."""

    new_edge_ids: tuple[str, ...]
    """Graph edge ids this document caused to be written this run —
    including the provenance-bearing SOURCE_DOCUMENT→field→node chain
    (invariant 3, Gate 14.5: "queryable end to end")."""

    detail: str
    """Human-readable specifics: the failure reason, the registry-gap
    detection summary, the ambiguous mention + candidate ids, or `""` on
    a clean `INGESTED`. Never a stack trace verbatim."""


@dataclass(frozen=True, slots=True)
class ConnectorFailure:
    """A whole `SourceConnector` failing for one run — reported as run
    data, not raised past the orchestrator's per-source boundary (spec
    §19.3). The other sources in the same request still run."""

    source: IngestionSourceKind
    principal: str
    reason: str
    is_auth_failure: bool
    """True when the cause was a missing / expired / revoked grant
    (`OAuthConnectionRequired`, `OAuthTokenRefreshFailed`,
    `OAuthScopeInsufficient` caught at the boundary) — the Connections UI
    shows a reconnect prompt. False for a transient fetch failure that
    survived backoff (`ConnectorFetchFailed`)."""


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    """The honest outcome of one orchestrator run — the type the
    `POST /ingest` handler returns, the voice path surfaces, and tests
    assert against. Never a bare success flag (PHASES.md Phase 14.5 CTO
    work item)."""

    run_id: str
    idempotency_scope: str
    started_at: datetime
    finished_at: datetime
    sources_scanned: tuple[IngestionSourceKind, ...]
    outcomes: tuple[DocumentIngestOutcome, ...]
    new_node_ids: tuple[str, ...]
    """Union of every `DocumentIngestOutcome.new_node_ids` — the single
    most demo-relevant field ("each new node linked into the graph
    view")."""
    connector_failures: tuple[ConnectorFailure, ...] = ()
    run_errors: tuple[str, ...] = ()
    """Run-level failures that are not tied to one document or one
    connector (e.g. the audit-log write failed, the dedupe store was
    unreachable). A non-empty tuple means the run is only partially
    trustworthy and the caller must surface that."""

    @property
    def documents_seen(self) -> int:
        return len(self.outcomes)

    @property
    def new_node_count(self) -> int:
        return len(self.new_node_ids)

    @property
    def counts(self) -> dict[str, int]:
        """Per-status tally keyed by `DocumentIngestStatus` value —
        directly serializable, directly assertable. Computed from
        `outcomes` so it can never drift from them."""
        tally: dict[str, int] = {status.value: 0 for status in DocumentIngestStatus}
        for outcome in self.outcomes:
            tally[outcome.status.value] += 1
        return tally


# ---------------------------------------------------------------------------
# The connector interface — one per provider, pure, zero I/O in the shape
# ---------------------------------------------------------------------------


class SourceConnector(Protocol):
    """The interface every provider connector implements (E3:
    `GmailConnector`, `OutlookConnector`; a Drive-picker fetch is a thin
    connector-shaped helper). Pure interface — a concrete connector does
    real HTTP and reads a refresh token from Secret Manager, but nothing
    in this Protocol names an SDK type, and `contracts/` imports no
    provider SDK.

    Synchronous, by deliberate choice (ADR-023): every existing GharOS
    agent, adapter, and tool is synchronous; the `POST /ingest` handler
    offloads the blocking run to a worker thread. There is no async
    benefit to expose here — the pipeline downstream (A2 → A3 → A5 →
    strategy → `GraphWriter`) is entirely synchronous.
    """

    kind: IngestionSourceKind

    def fetch_since(self, window: timedelta, *, principal: str) -> Sequence[RawIntakePayload]:
        """Fetch every item received within `window` of now for the
        account identified by `principal`.

        The connector resolves `principal` to a stored `OAuthCredential`,
        exchanges its Secret-Manager-held refresh token for an in-memory
        access token (never persisted), pages the provider's list API
        (Gmail `users.messages.list` `newer_than:1d` / Graph
        `receivedDateTime ge <iso>`), fetches each item, and maps it into
        `RawIntakePayload` in the `{headers, body}` shape the matching
        `app.adapters` normalizer already consumes. It MUST set
        `RawIntakePayload.headers[EXTERNAL_IDENTITY_HEADER]` on every
        payload.

        Raises:
            contracts.errors.OAuthConnectionRequired: no stored,
                unrevoked credential for `(provider, principal)`.
            contracts.errors.OAuthScopeInsufficient: the stored grant
                lacks a scope this fetch needs.
            contracts.errors.OAuthTokenRefreshFailed: the refresh-token
                exchange failed (revoked, expired 7-day test-mode token,
                provider outage).
            contracts.errors.ConnectorFetchFailed: a non-auth fetch
                failure that survived the connector's own retry/backoff.

        The orchestrator catches each of these at its per-source boundary
        and records a `ConnectorFailure` — they are never allowed to
        abort a multi-source run (spec §19.3).
        """
        ...


# ---------------------------------------------------------------------------
# Persistence protocols — E1 implements in backend/app/persistence/
# ---------------------------------------------------------------------------


class IngestionDedupeStore(Protocol):
    """Per-document idempotency index, keyed by `compute_content_hash`.
    The sibling of `contracts.repositories.IdempotencyStore` (which keys
    T3+ *tool* replays); this one keys *ingested documents* so a re-scan
    of the same window writes zero new nodes. E1: a small Firestore
    collection, not a graph node type — `contracts.graph_types` is
    unchanged this phase (ADR-023, ADR-021's zero-new-graph-types
    precedent)."""

    def seen(self, content_hash: str) -> str | None:
        """The SOURCE_DOCUMENT NodeId this `content_hash` was first
        ingested as, or `None` if never seen. Read before any stage
        runs for an item."""
        ...

    def record(
        self,
        content_hash: str,
        *,
        source_document_id: str,
        run_id: str,
        ingested_at: datetime,
    ) -> None:
        """Record a first successful ingest. Called exactly once per
        `INGESTED` outcome, after the graph write commits. A second
        `record` for the same `content_hash` is a defect (the caller
        checked `seen` first) — the implementation raises
        `contracts.errors.IdempotencyConflict` rather than overwrite."""
        ...


class OAuthCredentialStore(Protocol):
    """CRUD for `OAuthCredential` records. E1: a Firestore
    `oauth_credentials` collection, document id `f"{provider}:{principal}"`.
    Stores ONLY the `OAuthCredential` shape below — never token material.
    E3's OAuth routes call `put` / `mark_revoked`; E3's connectors call
    `get` / `touch_last_scan`; E3's `GET /connections` endpoint (for E4's
    surface) calls `list_active`."""

    def get(self, provider: OAuthProvider, principal: str) -> OAuthCredential | None: ...

    def list_active(self) -> tuple[OAuthCredential, ...]:
        """Every credential with `revoked_at is None`."""
        ...

    def put(self, credential: OAuthCredential) -> None:
        """Insert or replace the record for `(credential.provider,
        credential.principal)`. Used by the OAuth callback route after a
        successful consent exchange."""
        ...

    def mark_revoked(self, provider: OAuthProvider, principal: str, *, revoked_at: datetime) -> None:
        """Set `revoked_at` (a soft delete — `set, never overwritten`,
        matching the project's supersession discipline). The caller is
        separately responsible for destroying the Secret Manager version
        the record's `secret_ref` names."""
        ...

    def touch_last_scan(self, provider: OAuthProvider, principal: str, *, at: datetime) -> None:
        """Update `last_scan_at` after a connector run. Never changes any
        other field."""
        ...


# ---------------------------------------------------------------------------
# The persisted OAuth record — reference only, never token material
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OAuthCredential:
    """The complete persisted record for one connected account.

    **The refresh token is NOT a field here — by design, and this is
    load-bearing (spec §23: "financial credentials never touch a
    reasoning agent"; the same rule applies to every credential).** The
    refresh token lives only in Secret Manager, at the resource named by
    `secret_ref`. Access tokens are exchanged in memory for the duration
    of one run and never persisted anywhere. Nothing a reasoning agent
    can reach — not this record, not the graph, not an agent input —
    ever carries token material. Gate 14.5 proves this by test.
    """

    provider: OAuthProvider
    principal: str
    """The account identity: the email address (Google) or UPN
    (Microsoft) consent was granted for. Half of the Firestore document
    id `f"{provider.value}:{principal}"`."""

    granted_scopes: tuple[str, ...]
    """The scopes the provider actually granted (from the token
    response), not the scopes requested — the connector checks a fetch's
    required scope against this set and raises `OAuthScopeInsufficient`
    on a shortfall."""

    secret_ref: str
    """A Secret Manager resource name — e.g.
    `projects/<project>/secrets/gharos-oauth-refresh--google--alice-example-com/versions/latest`.
    A STRING pointer only. Resolving it to the actual refresh token is
    `app.adapters.secret_manager.SecretManagerAdapter`'s job, invoked
    only inside a connector, never by anything under
    `backend/app/agents/`."""

    connected_at: datetime
    last_scan_at: datetime | None = None
    revoked_at: datetime | None = None
    """Set once, on disconnect — never cleared, never overwritten. A
    record with `revoked_at` set is retained for the audit trail and
    shown as "disconnected" in the Connections UI; `list_active` filters
    it out."""

    @property
    def storage_key(self) -> str:
        """The Firestore document id E1 uses for this record."""
        return f"{self.provider.value}:{self.principal}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


__all__ = [
    "EXTERNAL_IDENTITY_HEADER",
    "INGESTION_CONTENT_HASH_VERSION",
    "SCANNING_SOURCE_KINDS",
    "ConnectorFailure",
    "DocumentIngestOutcome",
    "DocumentIngestStatus",
    "IngestionDedupeStore",
    "IngestionRequest",
    "IngestionRunResult",
    "IngestionSourceKind",
    "OAuthCredential",
    "OAuthCredentialStore",
    "OAuthProvider",
    "RawIntakePayload",
    "SourceConnector",
    "compute_content_hash",
]

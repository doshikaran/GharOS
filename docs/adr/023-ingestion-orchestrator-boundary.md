# ADR-023: The ingestion orchestrator boundary — one `POST /ingest` entry, one synchronous pipeline, idempotent per content hash (DEBT-009's repayment)

**Status:** accepted
**Phase:** 14.5
**Date:** 2026-08-29

## Context

DEBT-009 (opened Phase 7): **no phase built to date has an actual orchestrator wiring raw document → extraction → entity resolution → downstream writer agents together end to end, for any node type.** Every gate from Phase 1 through Phase 14 was verified by calling each agent / strategy directly with pre-assembled inputs. DEBT-004's attendance write-path gap and the Phase 13 voice-capture gap are the same gap in different channels. Phase 14.5 exists to close it: a single real wire, behind one HTTP entry point, driving the Phase 3 stages to committed graph nodes — and Gate 14.5 lists "DEBT-009 struck" as an explicit checklist item.

The Phase 3 stages already exist as real, tested, synchronous components:

| Stage | Component (owner) | Shape |
|---|---|---|
| normalize | the four `app.adapters` adapters (E3) | `IngestionAdapter.normalize(RawIntakePayload) -> NormalizedIntake` |
| A2 route | `app.agents.intake.intake_router` (E2) | `IntakeRouteResult` (classified type id + confidence, or triage) |
| A3 / A3b / A3c extract | `app.agents.intake.document_extraction` etc. (E2) | `ExtractionRunResult` → `tuple[ExtractedField, ...]` |
| A5 entity resolution | `app.agents.intake.entity_resolution` (E2) | `EntityResolutionResult` per mention |
| map to graph | the registered `ExtractionStrategy` (E2), via `app.adapters.document_registry` (E3) | `GraphMappingResult` (nodes + edges, each with `Provenance`) |
| commit | `contracts.repositories.GraphWriter` (E1) | provenance-guarded writes |

What is missing is only the connective tissue between them, and an honest per-document outcome record.

## Decision

### 1. One entry point, one path

`POST /ingest` (E3, `backend/app/api/ingest_router.py`) is the **only** way in. It accepts either a JSON body (a connector window-scan) or `multipart/form-data` (dragged-in files); the Google Drive picker path fetches the user-picked file's bytes server-side and joins the same way. The route handler's sole job is to build one `contracts.ingestion.IngestionRequest` (connector scans → `sources` + `window` + `principal`; uploads / picked Drive files → `inline_payloads`) and call:

```
IngestionOrchestrator.run(request: IngestionRequest) -> IngestionRunResult
```

`backend/app/pipelines/ingestion_orchestrator.py` (new module, new directory — ownership in §6). The orchestrator, per source and per inline payload, walks exactly this fixed sequence:

```
RawIntakePayload
  → compute_content_hash(...)                    # BEFORE any stage runs
  → IngestionDedupeStore.seen(hash)?  ── hit ──▶  DocumentIngestOutcome(DUPLICATE_SKIPPED, points at the original SOURCE_DOCUMENT)
  → RawPayloadStore.store(bytes)                  # durable raw bytes, get raw_payload_ref
  → matching app.adapters normalizer .normalize() → NormalizedIntake
  → A2 IntakeRouter                               # unresolved / registry gap → REGISTRY_GAP path (generic strategy, log gap, triage)
  → A7 Graph Builder writes the SOURCE_DOCUMENT node (channel, raw_payload_ref, document_type, provenance)
  → A3 / A3b extract against the type's field_schema  # below floor → EXTRACTION_FAILED (SOURCE_DOCUMENT + raw retained)
  → A5 entity resolution over the extracted mentions
        └─ AmbiguousEntity(hard_constraint_bearing=True) → ENTITY_RESOLUTION_ESCALATED (no typed mapping written; escalate with the doc)
  → registered ExtractionStrategy.map_to_graph(source_document_id, extracted_fields, deriving_agent) → GraphMappingResult
  → GraphWriter.write_node / write_edge for every node & edge in the result  # provenance guard enforces invariant 3
  → IngestionDedupeStore.record(hash, source_document_id, run_id, ingested_at)
  → DocumentIngestOutcome(INGESTED, new_node_ids, new_edge_ids)
```

Each stage is `structlog`-logged with `run_id`, `content_hash`, the stage name, and the outcome. The orchestrator writes **one `AuditLog.append` record for the run** (`action_type="ingestion_run"`, payload: `idempotency_scope`, `triggered_by`, `sources`, `window`) **before** it writes any graph node — invariant #2's posture applied to ingestion even though graph writes are T3-internal.

### 2. A synchronous orchestrator, not ADK-runner code, not truly async

**Recommendation: a plain synchronous orchestrator class.** Justification:

- Every stage it sequences (`normalize`, A2, A3, A5, `map_to_graph`, `GraphWriter`) is already synchronous and blocking (Gemini calls via `GeminiClient` are sync; Firestore writes are sync). Wrapping them in `async def` would produce sync code in an async costume, with no concurrency actually expressed.
- ADK's value is dynamic agent composition — an LLM choosing the next tool / sub-agent in a loop. This pipeline has **no dynamic routing**: it is a fixed 6-stage imperative sequence with typed branches on typed results. Spec §7.3 itself calls it "the four-stage pipeline". An ADK runner here would add a framework layer and buy nothing; DEBT-009 explicitly offered "an explicit, reasoned decision that ADK's agent-composition model already provides this" as an option — this is the reasoned decision that it does **not** apply here, because the existing per-stage agents are plain classes and there is no routing for ADK to own.
- `SourceConnector.fetch_since` is likewise synchronous in the frozen contract (`contracts.ingestion`), for the same reason and for consistency with every other GharOS adapter/tool.

`POST /ingest` is declared `async def` (FastAPI convention) but offloads the blocking `orchestrator.run(...)` to a worker thread via `fastapi.concurrency.run_in_threadpool`, so the event loop is never blocked for the length of a scan. This matches how the codebase already handles blocking work behind async route handlers.

### 3. Idempotent per `SourceDocument` content hash — exactly what is hashed

`contracts.ingestion.compute_content_hash` is the frozen definition. `sha256`, `\x1e`-separated, in this fixed order:

1. `INGESTION_CONTENT_HASH_VERSION` (`"gharos.ingest.v1"`)
2. `IngestionSourceKind.value` (`"gmail"` / `"outlook"` / `"drive_picker"` / `"direct_upload"`)
3. **`external_identity`** — `RawIntakePayload.headers[EXTERNAL_IDENTITY_HEADER]`: the provider's immutable per-item id. Gmail / Microsoft Graph → the message `id`. Drive picker → `f"{file_id}:{head_revision_id}"`. `direct_upload` → `""` (empty, so items 4-5 carry the whole identity for that path).
4. `media_type` (the MIME type)
5. `sha256(RawIntakePayload.binary or b"")` hex — pre-hashed so a large PDF/image contributes a fixed-length input.
6. `unicodedata.normalize("NFC", NormalizedIntake.text_content or "")` — the **normalized** text (post-adapter, so re-forwarded quoting boilerplate does not defeat dedupe).

The orchestrator computes this **before any stage runs** and calls `IngestionDedupeStore.seen(hash)`. A hit → `DUPLICATE_SKIPPED`, zero writes, the outcome points at the original SOURCE_DOCUMENT NodeId. `IngestionDedupeStore` (E1) is a small Firestore collection — the sibling of `contracts.repositories.IdempotencyStore` — **not** a new `contracts.graph_types` field or node type (ADR-021's zero-new-graph-types precedent; a queryable `SOURCE_DOCUMENT.content_hash` field plus a new `GraphReader` method would be a heavier change for a concern that is an operational index, not graph traversal).

Result: re-running the same 24-hour scan the next minute produces an `IngestionRunResult` whose every outcome is `DUPLICATE_SKIPPED` and whose `new_node_ids` is empty (Gate 14.5).

### 4. Honest partial success — `IngestionRunResult`, never a bare flag

- Per-document: exactly one `DocumentIngestStatus` per item (`ingested` / `duplicate_skipped` / `extraction_failed` / `registry_gap` / `entity_resolution_escalated` / `error`). A failed extraction is a **visible** `EXTRACTION_FAILED` outcome with a `detail`, never a silent drop.
- Per-connector: `OAuthConnectionRequired` / `OAuthTokenRefreshFailed` / `OAuthScopeInsufficient` / `ConnectorFetchFailed` raised inside `fetch_since` are **caught at the orchestrator's per-source boundary** and recorded as a `ConnectorFailure` on the result; the other sources in the same request still run (spec §19.3: "failures reported, not hidden"). These exceptions propagate out of `POST /ingest` **only** when they are the whole request's precondition failure (a single-source request against an unconnected account) — then the handler maps them to `409`/`428` with a "connect the account" body.
- Run-level: `IngestionRunResult.run_errors` for failures tied to neither one document nor one connector (dedupe store unreachable, audit write failed).

### 5. `map_to_graph` is unchanged; the strategy-level "resolved owner" gap stays open

`ExtractionStrategy.map_to_graph`'s frozen signature (`source_document_id`, `extracted_fields`, `deriving_agent` → `GraphMappingResult`) is **not** changed this phase. The orchestrator runs A5 for two things: (a) resolving the sender and body mentions to existing PERSON/VENDOR nodes for provenance context, handed to the Consequence Engine on the downstream handoff; (b) the hard-constraint escalation guard (`ENTITY_RESOLUTION_ESCALATED`). Strategies that need a *capability-aware resolved owner* to form an `owned_by` edge (permission slip, attendance register) still "leave that to a downstream agent with real graph access" — DEBT-004 repayment condition (b) remains open and is explicitly **not** closed by 14.5. 14.5's wire runs as far as `map_to_graph` + the Consequence-Engine handoff; ownership edges form there, as they always have. Adding a `resolved_entities` parameter to `map_to_graph` is deferred to whichever phase first demonstrates that strategy-level path end to end, per this project's "design against a real consumer" discipline (DEBT-005/006/010/011).

### 6. File-ownership assignment for the new surface area

`backend/app/pipelines/` is a new directory, absent from the `gharos-standards` ownership table.

| Path | Owner | Rationale |
|---|---|---|
| `backend/app/pipelines/` (new) — `ingestion_orchestrator.py` and any siblings | **E3** | E3 leads Phase 14.5, owns the four `app.adapters` normalizers, the document-type registry, `app.events`, and deployment. The orchestrator is connective wiring over adapters + a registry, squarely E3's concern. |
| `backend/app/api/ingest_router.py` (new), `backend/app/api/oauth_router.py` (new) | **E3** | Consistent with `voice_router.py` (E3) — a router is owned by the surface's owner. `main.py` router-registration lines are made by the router's owner, as in Phase 13. |
| `OAuthCredential` / `oauth_pending` / `IngestionDedupeStore` **persistence** — `backend/app/persistence/oauth_credential_store.py`, the dedupe collection | **E1** | E1 owns `backend/app/persistence/`. These implement `contracts.ingestion` Protocols; they store only the frozen record shapes, no token material. |
| A2 confirming a real Gmail/Outlook message routes end to end; **A67** `ingest.scan_mailbox` intent + the deterministic enumerated check; the real-mail extraction honesty note | **E2** | E2 owns `backend/app/agents/`. |
| The **Ingestion / Connections** frontend surface + the live run view | **E4** | E4 owns `frontend/`. Reuses `/graph/stream`; no new endpoint. |

`gharos-standards`' ownership table is updated by the CTO to add the `backend/app/pipelines/` → E3 row as part of this ADR landing.

### 7. The voice trigger

A67 gains an `ingest.scan_mailbox` intent (E2), enumerated and checked deterministically **independent of the LLM call** — mirroring A68's `_requires_confirmation` pattern in `voice_intent_classifier_agent.py` (a pure function over structural signals, not model discretion). It routes through a new `VoiceRoutingCallbacks.on_scan_mailbox` hook (E2 adds the field to `app.voice.session_types` — E2's tree) to the **orchestrator**, constructing an `IngestionRequest(sources=(GMAIL, OUTLOOK, ...), window=24h, principal=<the household's connected principal>, triggered_by="voice", idempotency_scope=f"voice-turn:{turn_id}")`. It is **never** routed to an action tool and carries **no** `RiskTier` — ingestion is a read that writes only T3-internal graph nodes; invariant #8 (voice confers no action capability) is preserved because nothing on this path can reach a T4/T5/T6 tool. The `WS /voice/session` frame handling surfaces the resulting `IngestionRunResult` to the same live run view the text path uses.

## Alternatives considered

1. **A per-channel entry point (a `/ingest/gmail`, a `/ingest/upload`, …).** Rejected: Gate 14.5 says "the one `POST /ingest` wire" and "reach the graph through the one `POST /ingest` wire" — a single entry is the point, and it is what makes "does *anything* actually construct this node in production" answerable with one code path.
2. **An ADK `SequentialAgent` / runner composing A2→A3→A5→writer.** Rejected — see §2. No dynamic routing to own; adds a framework layer over plain synchronous classes.
3. **A truly async orchestrator with `asyncio.gather` across sources.** Rejected for this phase: the downstream stages are sync and blocking, so real concurrency would need each stage made async or thread-pooled per source — real work with no gate-relevant payoff (two mailboxes, ~24h each, is not a latency problem). `run_in_threadpool` at the route boundary is sufficient. A later phase may parallelise across sources if scan latency ever matters.
4. **Hash only the provider message id (ignore body/bytes).** Rejected: a genuinely edited resend (new body) or a new Drive revision must count as new; including the normalized content + `headRevisionId` gets that right, while the provider id keeps a plain re-fetch a clean dedupe.
5. **Store `content_hash` as a queryable `SOURCE_DOCUMENT` field + new `GraphReader.source_document_by_content_hash`.** Rejected: it is an operational dedupe index, not graph traversal; a Protocol-based store keeps `contracts.graph_types` frozen (ADR-021 precedent) and mirrors the existing `IdempotencyStore`.

## Consequences

- **New (E3):** `backend/app/pipelines/ingestion_orchestrator.py`, `backend/app/api/ingest_router.py`, `backend/app/api/oauth_router.py`, `backend/app/adapters/oauth/`, `GmailConnector` / `OutlookConnector` / the Drive-picker fetch helper (`backend/app/adapters/connectors/`), the one-line re-home in `backend/app/adapters/ingestion.py` (`RawIntakePayload` now `from contracts.ingestion import RawIntakePayload`, kept in `__all__`; `resolve_raw_payload_ref` + `STORAGE_REF_HEADER` stay), `main.py` router registrations, new `settings.py` OAuth fields, the new Cloud Scheduler / infra as needed for deploy, a real backend redeploy.
- **New (E1):** `backend/app/persistence/oauth_credential_store.py` (+ `oauth_pending`), the `IngestionDedupeStore` implementation, Firestore collections `oauth_credentials` and the dedupe index. All against `contracts.ingestion` Protocols.
- **New (E2):** A67 `ingest.scan_mailbox` intent + deterministic check + prompt version bump (ADR-003), the `on_scan_mailbox` callback field on `app.voice.session_types`, A2 real-message confirmation, `docs/` honesty note comparing real-mail A3 extraction quality to the golden-file baseline (E2 writes this under a location it owns or hands the CTO the text).
- **New (E4):** `frontend/` Connections surface + live run view, reusing `/graph/stream`.
- **Contracts (CTO, this phase):** `contracts/ingestion.py` (new), `contracts/errors.py` (the `IngestionError` family). `contracts/graph_types.py`, `contracts/repositories.py`, `contracts/events.py`, `contracts/actions.py`, `contracts/tools.py`, `contracts/agents.py` — **unchanged**.
- **DEBT-009** is struck when Gate 14.5's checklist passes: a real orchestrator exists and runs a real raw-document-to-graph flow live, with a test proving it. **DEBT-004** repayment condition (a) is thereby satisfied for attendance too *if* an attendance register is run through the wire; condition (b) (strategy-level resolved owner) stays open.
- **`gharos-standards` ownership table** gains `backend/app/pipelines/` → E3.

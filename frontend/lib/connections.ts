/**
 * TypeScript mirror of the Phase 14.5 ingestion-connector wire contract
 * (`contracts/ingestion.py`, frozen; ADR-022 OAuth flow, ADR-023 the
 * one `POST /ingest` orchestrator boundary).
 *
 * Source of truth, read directly rather than guessed at:
 *   - `contracts/ingestion.py` — `IngestionSourceKind`, `OAuthProvider`,
 *     `DocumentIngestStatus`, `DocumentIngestOutcome`, `ConnectorFailure`,
 *     `IngestionRunResult`, `OAuthCredential`.
 *   - `docs/adr/022-oauth-in-a-backend-only-architecture.md` — the
 *     `GET /oauth/{provider}/start` consent-start route and the
 *     `POST /connections/{provider}/{principal}/disconnect` route.
 *   - `docs/adr/023-ingestion-orchestrator-boundary.md` — the single
 *     `POST /ingest` entry (JSON window-scan / multipart upload / JSON
 *     Drive-picker file-id list), returning an `IngestionRunResult`.
 *
 * These contracts are owned by the CTO (`contracts/`) and implemented by
 * E3 (`backend/app/api/ingest_router.py`, `oauth_router.py`,
 * `backend/app/pipelines/ingestion_orchestrator.py`) and E1
 * (`backend/app/persistence/oauth_credential_store.py`). This file
 * mirrors their shape; it never redefines it.
 *
 * **Wire key convention:** `snake_case`, kept verbatim from the Python
 * dataclass field names, matching this codebase's existing discipline for
 * a real (not fixture) HTTP surface — `lib/graph-types.ts` /
 * `lib/graph-api.ts` do the same. Enum wire values are the Python
 * `.value` strings. `datetime` fields are ISO 8601 strings. `timedelta`
 * `window` is sent as an integer `window_seconds` (ADR-023's own
 * `POST /ingest` body shape and PHASES.md Phase 14.5's example).
 *
 * **`secret_ref` is deliberately absent from `ConnectionRecord`** — spec
 * §23 / ADR-022 §2: nothing a browser (or a reasoning agent) can reach
 * ever carries token material or a pointer to it. `GET /connections`
 * serializes `OAuthCredential` MINUS `secret_ref`.
 */

// ---------------------------------------------------------------------------
// Enums — `contracts.ingestion`
// ---------------------------------------------------------------------------

/** `contracts.ingestion.OAuthProvider` — the authorization server a
 * stored credential belongs to. One Google grant backs both the Gmail
 * scan and the Drive picker. */
export type OAuthProvider = "google" | "microsoft";

export const OAUTH_PROVIDERS: readonly OAuthProvider[] = ["google", "microsoft"];

/** `contracts.ingestion.IngestionSourceKind`. */
export type IngestionSourceKind = "gmail" | "outlook" | "drive_picker" | "direct_upload";

/** `contracts.ingestion.SCANNING_SOURCE_KINDS` — the kinds a window-scan
 * applies to (a time-bounded remote-mailbox read). `drive_picker` and
 * `direct_upload` deliver explicitly chosen items, not a scan. */
export const SCAN_SOURCE_KINDS: readonly IngestionSourceKind[] = ["gmail", "outlook"];

/** `contracts.ingestion.DocumentIngestStatus` — the one honest per-document
 * outcome of an orchestrator run. Every item ends on exactly one; there
 * is no silent drop (Gate 14.5). */
export type DocumentIngestStatus =
  | "ingested"
  | "duplicate_skipped"
  | "extraction_failed"
  | "registry_gap"
  | "entity_resolution_escalated"
  | "error";

export const DOCUMENT_INGEST_STATUSES: readonly DocumentIngestStatus[] = [
  "ingested",
  "duplicate_skipped",
  "extraction_failed",
  "registry_gap",
  "entity_resolution_escalated",
  "error",
];

// ---------------------------------------------------------------------------
// Record shapes — `contracts.ingestion`
// ---------------------------------------------------------------------------

/** `GET /connections` array element — `contracts.ingestion.OAuthCredential`
 * serialized WITHOUT `secret_ref`. A record with `revoked_at` set is a
 * soft-deleted (disconnected) account, retained for the audit trail. */
export interface ConnectionRecord {
  readonly provider: OAuthProvider;
  readonly principal: string;
  readonly granted_scopes: readonly string[];
  readonly connected_at: string;
  readonly last_scan_at: string | null;
  readonly revoked_at: string | null;
}

/** `contracts.ingestion.DocumentIngestOutcome`. */
export interface DocumentIngestOutcome {
  readonly content_hash: string;
  readonly source: IngestionSourceKind;
  readonly status: DocumentIngestStatus;
  readonly source_document_id: string | null;
  readonly external_ref: string | null;
  readonly classified_type_id: string | null;
  readonly new_node_ids: readonly string[];
  readonly new_edge_ids: readonly string[];
  readonly detail: string;
}

/** `contracts.ingestion.ConnectorFailure` — a whole connector failing for
 * one run, reported as run data. `is_auth_failure === true` means a
 * missing / expired / revoked grant: the Connections surface must show a
 * reconnect prompt, never a silent empty scan (Gate 14.5, invariant 7). */
export interface ConnectorFailure {
  readonly source: IngestionSourceKind;
  readonly principal: string;
  readonly reason: string;
  readonly is_auth_failure: boolean;
}

/** `contracts.ingestion.IngestionRunResult` — the honest outcome of one
 * orchestrator run: the `POST /ingest` response body, and (per ADR-023
 * §7) the payload the voice path surfaces to the same run view. */
export interface IngestionRunResult {
  readonly run_id: string;
  readonly idempotency_scope: string;
  readonly started_at: string;
  readonly finished_at: string;
  readonly sources_scanned: readonly IngestionSourceKind[];
  readonly outcomes: readonly DocumentIngestOutcome[];
  readonly new_node_ids: readonly string[];
  readonly connector_failures: readonly ConnectorFailure[];
  readonly run_errors: readonly string[];
}

// ---------------------------------------------------------------------------
// Single-household framing
// ---------------------------------------------------------------------------

/**
 * The single household id every Phase 0-15 deployment uses
 * (`contracts.events.InboundEnvelope.household_id` — "every deployment
 * MUST use exactly one value for it"). No backend constant exposes it as
 * of Phase 14.5, so it is pinned here and **MUST match** the value E3's
 * `POST /ingest` handler and the orchestrator's audit record use. If E3
 * chooses a different literal, change it here (one line) rather than
 * scattering it.
 */
export const DEMO_HOUSEHOLD_ID = "gharos-demo-household";

// ---------------------------------------------------------------------------
// Metadata every `POST /ingest` request carries
// ---------------------------------------------------------------------------

export interface IngestMeta {
  /** `IngestionRequest.idempotency_scope` — a caller-chosen scope string
   * that lets a retried identical run be recognised. */
  readonly idempotencyScope: string;
  /** `IngestionRequest.triggered_by` — a PERSON NodeId string for a
   * person-triggered scan, `"manual"`, or `"voice"`. */
  readonly triggeredBy: string;
  /** `IngestionRequest.household_id`. */
  readonly householdId: string;
}

/** A timestamp-based `idempotency_scope`, matching the contract's own
 * examples (`"manual-scan:2026-08-29T14:00Z"`). */
export function newIdempotencyScope(prefix: string): string {
  return `${prefix}:${new Date().toISOString()}`;
}

// ---------------------------------------------------------------------------
// Provider / scope display helpers
// ---------------------------------------------------------------------------

const PROVIDER_LABEL: Record<OAuthProvider, string> = {
  google: "Google — Gmail and Drive",
  microsoft: "Microsoft — Outlook",
};

export function providerDisplayLabel(provider: OAuthProvider): string {
  return PROVIDER_LABEL[provider];
}

const SOURCE_LABEL: Record<IngestionSourceKind, string> = {
  gmail: "Gmail",
  outlook: "Outlook",
  drive_picker: "Google Drive",
  direct_upload: "Uploaded file",
};

export function ingestionSourceLabel(source: IngestionSourceKind): string {
  return SOURCE_LABEL[source];
}

/** The window-scan source kinds a provider grant can drive. Drive is
 * picker-only (ADR-023: no library sweep), so it is never a scan kind. */
export function providerScanKinds(provider: OAuthProvider): readonly IngestionSourceKind[] {
  return provider === "google" ? ["gmail"] : ["outlook"];
}

const SCOPE_LABEL: Readonly<Record<string, string>> = {
  openid: "Sign-in identity",
  email: "Email address",
  profile: "Basic profile",
  offline_access: "Keep access when you are away",
  "https://www.googleapis.com/auth/gmail.readonly": "Read your Gmail (read-only)",
  "https://www.googleapis.com/auth/drive.file": "Open only the Drive files you pick",
  "Mail.Read": "Read your Outlook mail",
  "https://graph.microsoft.com/Mail.Read": "Read your Outlook mail",
};

/** A plain-language label for one granted OAuth scope, so a household
 * member can see exactly what was granted (Phase 14.5 E4 brief). The raw
 * scope string is still shown alongside this. */
export function scopePlainLabel(scope: string): string {
  return SCOPE_LABEL[scope] ?? scope;
}

// ---------------------------------------------------------------------------
// URLs
// ---------------------------------------------------------------------------

/** `GET /oauth/{provider}/start` (ADR-022 §1) — a full-page browser
 * redirect target, NOT a `fetch`: it 302s the browser to the provider's
 * consent screen. */
export function oauthStartUrl(baseUrl: string, provider: OAuthProvider): string {
  return `${baseUrl}/oauth/${provider}/start`;
}

/** Deep link into `/graph` with a node's inspector opened
 * (`GraphExplorer` reads `?node=` — see `app/(shell)/graph/page.tsx`). */
export function graphNodeHref(nodeId: string): string {
  return `/graph?node=${encodeURIComponent(nodeId)}`;
}

// ---------------------------------------------------------------------------
// Status tally — computed from `outcomes`, never trusted from the wire
// (mirrors `IngestionRunResult.counts`, which the contract itself
// computes from `outcomes` "so it can never drift from them").
// ---------------------------------------------------------------------------

export function computeStatusCounts(
  outcomes: readonly DocumentIngestOutcome[],
): Record<DocumentIngestStatus, number> {
  const tally: Record<DocumentIngestStatus, number> = {
    ingested: 0,
    duplicate_skipped: 0,
    extraction_failed: 0,
    registry_gap: 0,
    entity_resolution_escalated: 0,
    error: 0,
  };
  for (const outcome of outcomes) {
    tally[outcome.status] += 1;
  }
  return tally;
}

// ---------------------------------------------------------------------------
// Wire result types — a failed call is reported as a typed failure with
// the real detail, never collapsed into one generic message (mirrors
// `lib/status-checks.ts` / gharos-standards safety invariant #7 in
// spirit).
// ---------------------------------------------------------------------------

export type WireFailureKind = "network" | "timeout" | "http-error" | "invalid-json";

const WIRE_FAILURE_LABEL: Record<WireFailureKind, string> = {
  network: "Could not reach the server",
  timeout: "The server did not respond in time",
  "http-error": "The server returned an error",
  "invalid-json": "The server response could not be read",
};

export function wireFailureLabel(kind: WireFailureKind): string {
  return WIRE_FAILURE_LABEL[kind];
}

export interface WireSuccess<T> {
  readonly ok: true;
  readonly data: T;
  readonly httpStatus: number;
}

export interface WireFailure {
  readonly ok: false;
  readonly kind: WireFailureKind;
  readonly message: string;
  readonly httpStatus?: number;
  readonly body?: string;
}

export type WireResult<T> = WireSuccess<T> | WireFailure;

const CONNECTIONS_TIMEOUT_MS = 15_000;
const INGEST_TIMEOUT_MS = 120_000;

function toFailure(err: unknown): WireFailure {
  if (err instanceof DOMException && err.name === "AbortError") {
    return { ok: false, kind: "timeout", message: "Request timed out with no response." };
  }
  const message = err instanceof Error ? err.message : String(err);
  return { ok: false, kind: "network", message };
}

async function readBody(response: Response): Promise<{ text: string; json: unknown; jsonOk: boolean }> {
  const text = await response.text().catch(() => "");
  if (text.length === 0) return { text, json: null, jsonOk: false };
  try {
    return { text, json: JSON.parse(text) as unknown, jsonOk: true };
  } catch {
    return { text, json: null, jsonOk: false };
  }
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  parse: (raw: unknown) => T | null,
): Promise<WireResult<T>> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const { text, json, jsonOk } = await readBody(response);
    if (!response.ok) {
      return {
        ok: false,
        kind: "http-error",
        message: `HTTP ${response.status} ${response.statusText}`.trim(),
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    if (!jsonOk) {
      return {
        ok: false,
        kind: "invalid-json",
        message: "The server answered but the body was not valid JSON.",
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    const parsed = parse(json);
    if (parsed === null) {
      return {
        ok: false,
        kind: "invalid-json",
        message: "The server response did not match the expected shape.",
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    return { ok: true, data: parsed, httpStatus: response.status };
  } catch (err) {
    return toFailure(err);
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Parsers — every response is untyped JSON off the wire; narrow it here,
// return null (never throw) on anything malformed.
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringArray(value: unknown): readonly string[] | null {
  if (!Array.isArray(value)) return null;
  return value.every((item) => typeof item === "string") ? (value as string[]) : null;
}

function isSourceKind(value: unknown): value is IngestionSourceKind {
  return (
    value === "gmail" || value === "outlook" || value === "drive_picker" || value === "direct_upload"
  );
}

function isIngestStatus(value: unknown): value is DocumentIngestStatus {
  return typeof value === "string" && (DOCUMENT_INGEST_STATUSES as readonly string[]).includes(value);
}

function isProvider(value: unknown): value is OAuthProvider {
  return value === "google" || value === "microsoft";
}

export function parseConnectionRecords(raw: unknown): ConnectionRecord[] | null {
  if (!Array.isArray(raw)) return null;
  const records: ConnectionRecord[] = [];
  for (const item of raw) {
    if (!isRecord(item)) return null;
    const scopes = asStringArray(item.granted_scopes);
    if (
      !isProvider(item.provider) ||
      typeof item.principal !== "string" ||
      scopes === null ||
      typeof item.connected_at !== "string" ||
      !(typeof item.last_scan_at === "string" || item.last_scan_at === null) ||
      !(typeof item.revoked_at === "string" || item.revoked_at === null)
    ) {
      return null;
    }
    records.push({
      provider: item.provider,
      principal: item.principal,
      granted_scopes: scopes,
      connected_at: item.connected_at,
      last_scan_at: item.last_scan_at,
      revoked_at: item.revoked_at,
    });
  }
  return records;
}

function parseOutcome(raw: unknown): DocumentIngestOutcome | null {
  if (!isRecord(raw)) return null;
  const newNodeIds = asStringArray(raw.new_node_ids);
  const newEdgeIds = asStringArray(raw.new_edge_ids);
  if (
    typeof raw.content_hash !== "string" ||
    !isSourceKind(raw.source) ||
    !isIngestStatus(raw.status) ||
    !(typeof raw.source_document_id === "string" || raw.source_document_id === null) ||
    !(typeof raw.external_ref === "string" || raw.external_ref === null) ||
    !(typeof raw.classified_type_id === "string" || raw.classified_type_id === null) ||
    newNodeIds === null ||
    newEdgeIds === null ||
    typeof raw.detail !== "string"
  ) {
    return null;
  }
  return {
    content_hash: raw.content_hash,
    source: raw.source,
    status: raw.status,
    source_document_id: raw.source_document_id,
    external_ref: raw.external_ref,
    classified_type_id: raw.classified_type_id,
    new_node_ids: newNodeIds,
    new_edge_ids: newEdgeIds,
    detail: raw.detail,
  };
}

function parseConnectorFailure(raw: unknown): ConnectorFailure | null {
  if (!isRecord(raw)) return null;
  if (
    !isSourceKind(raw.source) ||
    typeof raw.principal !== "string" ||
    typeof raw.reason !== "string" ||
    typeof raw.is_auth_failure !== "boolean"
  ) {
    return null;
  }
  return {
    source: raw.source,
    principal: raw.principal,
    reason: raw.reason,
    is_auth_failure: raw.is_auth_failure,
  };
}

/**
 * Narrows a raw, already-`JSON.parse`d `IngestionRunResult` (the
 * `POST /ingest` response, or the voice path's `ingestion_run` frame per
 * ADR-023 §7), or `null` if it does not match the frozen shape.
 */
export function parseIngestionRunResult(raw: unknown): IngestionRunResult | null {
  if (!isRecord(raw)) return null;
  if (
    typeof raw.run_id !== "string" ||
    typeof raw.idempotency_scope !== "string" ||
    typeof raw.started_at !== "string" ||
    typeof raw.finished_at !== "string" ||
    !Array.isArray(raw.sources_scanned) ||
    !Array.isArray(raw.outcomes) ||
    !Array.isArray(raw.new_node_ids)
  ) {
    return null;
  }
  if (!raw.sources_scanned.every(isSourceKind)) return null;
  const newNodeIds = asStringArray(raw.new_node_ids);
  if (newNodeIds === null) return null;

  const outcomes: DocumentIngestOutcome[] = [];
  for (const item of raw.outcomes) {
    const outcome = parseOutcome(item);
    if (outcome === null) return null;
    outcomes.push(outcome);
  }

  const failuresRaw = Array.isArray(raw.connector_failures) ? raw.connector_failures : [];
  const connectorFailures: ConnectorFailure[] = [];
  for (const item of failuresRaw) {
    const failure = parseConnectorFailure(item);
    if (failure === null) return null;
    connectorFailures.push(failure);
  }

  const runErrors = Array.isArray(raw.run_errors) ? asStringArray(raw.run_errors) : [];
  if (runErrors === null) return null;

  return {
    run_id: raw.run_id,
    idempotency_scope: raw.idempotency_scope,
    started_at: raw.started_at,
    finished_at: raw.finished_at,
    sources_scanned: raw.sources_scanned,
    outcomes,
    new_node_ids: newNodeIds,
    connector_failures: connectorFailures,
    run_errors: runErrors,
  };
}

// ---------------------------------------------------------------------------
// GET /connections
// ---------------------------------------------------------------------------

/**
 * `GET /connections` — every stored `OAuthCredential` (active and
 * soft-deleted), serialized without `secret_ref`. E3 may instead return
 * only active records; this client handles both (it labels a record with
 * `revoked_at` set as "disconnected").
 */
export async function fetchConnections(baseUrl: string): Promise<WireResult<ConnectionRecord[]>> {
  return requestJson<ConnectionRecord[]>(
    `${baseUrl}/connections`,
    { method: "GET", headers: { Accept: "application/json" } },
    CONNECTIONS_TIMEOUT_MS,
    parseConnectionRecords,
  );
}

// ---------------------------------------------------------------------------
// POST /connections/{provider}/{principal}/disconnect
// ---------------------------------------------------------------------------

/**
 * `POST /connections/{provider}/{principal}/disconnect` (ADR-022 §5) —
 * best-effort provider revoke, soft-delete of the record, and Secret
 * Manager version destruction, all server-side. A 2xx means done; the
 * response body is not required.
 */
export async function disconnectConnection(
  baseUrl: string,
  provider: OAuthProvider,
  principal: string,
): Promise<WireResult<null>> {
  const url = `${baseUrl}/connections/${provider}/${encodeURIComponent(principal)}/disconnect`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CONNECTIONS_TIMEOUT_MS);
  try {
    const response = await fetch(url, { method: "POST", signal: controller.signal });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      return {
        ok: false,
        kind: "http-error",
        message: `HTTP ${response.status} ${response.statusText}`.trim(),
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    return { ok: true, data: null, httpStatus: response.status };
  } catch (err) {
    return toFailure(err);
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// POST /ingest — the one wire (ADR-023 §1)
// ---------------------------------------------------------------------------

/**
 * The result of one `POST /ingest` submission.
 *
 * `reconnect-required` is the precondition-failure branch ADR-023 §4
 * describes: a single-source request against an account with no valid
 * grant returns `409` / `428`, and the surface renders it as a reconnect
 * prompt — the same treatment a `ConnectorFailure(is_auth_failure=true)`
 * inside a multi-source run gets. It is never shown as a generic error
 * and never as a silent empty result (Gate 14.5, invariant 7).
 */
export type IngestSubmitResult =
  | { readonly status: "ok"; readonly run: IngestionRunResult }
  | {
      readonly status: "reconnect-required";
      readonly provider: OAuthProvider | null;
      readonly principal: string | null;
      readonly message: string;
    }
  | {
      readonly status: "error";
      readonly kind: WireFailureKind;
      readonly message: string;
      readonly httpStatus?: number;
      readonly body?: string;
    };

function reconnectFromBody(bodyText: string, httpStatus: number): IngestSubmitResult {
  let provider: OAuthProvider | null = null;
  let principal: string | null = null;
  let detail = `The account needs to be reconnected (HTTP ${httpStatus}).`;
  try {
    const parsed: unknown = JSON.parse(bodyText);
    if (isRecord(parsed)) {
      if (isProvider(parsed.provider)) provider = parsed.provider;
      if (typeof parsed.principal === "string") principal = parsed.principal;
      if (typeof parsed.detail === "string" && parsed.detail.length > 0) detail = parsed.detail;
    }
  } catch {
    if (bodyText.length > 0) detail = bodyText;
  }
  return { status: "reconnect-required", provider, principal, message: detail };
}

async function submitIngest(baseUrl: string, init: RequestInit): Promise<IngestSubmitResult> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), INGEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${baseUrl}/ingest`, { ...init, signal: controller.signal });
    const { text, json, jsonOk } = await readBody(response);

    if (response.status === 409 || response.status === 428) {
      return reconnectFromBody(text, response.status);
    }
    if (!response.ok) {
      return {
        status: "error",
        kind: "http-error",
        message: `HTTP ${response.status} ${response.statusText}`.trim(),
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    if (!jsonOk) {
      return {
        status: "error",
        kind: "invalid-json",
        message: "The scan finished but its result could not be read (invalid JSON).",
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    const run = parseIngestionRunResult(json);
    if (run === null) {
      return {
        status: "error",
        kind: "invalid-json",
        message: "The scan result did not match the expected shape.",
        httpStatus: response.status,
        body: text || undefined,
      };
    }
    return { status: "ok", run };
  } catch (err) {
    const failure = toFailure(err);
    return { status: "error", kind: failure.kind, message: failure.message };
  } finally {
    clearTimeout(timeoutId);
  }
}

export interface StartScanArgs {
  readonly sources: readonly IngestionSourceKind[];
  readonly windowSeconds: number;
  readonly principal: string;
  readonly meta: IngestMeta;
}

/**
 * `POST /ingest` as a connector window-scan (`application/json`). ADR-023
 * §7 / PHASES.md Phase 14.5's own example body:
 * `{ sources, window_seconds, principal, idempotency_scope, triggered_by,
 * household_id }`. Single-principal per run (ADR-022).
 */
export async function startScan(baseUrl: string, args: StartScanArgs): Promise<IngestSubmitResult> {
  return submitIngest(baseUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      sources: args.sources,
      window_seconds: args.windowSeconds,
      principal: args.principal,
      idempotency_scope: args.meta.idempotencyScope,
      triggered_by: args.meta.triggeredBy,
      household_id: args.meta.householdId,
    }),
  });
}

/**
 * `POST /ingest` as a file upload (`multipart/form-data`) — dragged-in
 * images / PDFs, reusing `document_upload_adapter.py` server-side. Each
 * file is a `files` part; the run metadata rides as form fields.
 */
export async function uploadFilesForIngest(
  baseUrl: string,
  files: readonly File[],
  meta: IngestMeta,
): Promise<IngestSubmitResult> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  form.append("idempotency_scope", meta.idempotencyScope);
  form.append("triggered_by", meta.triggeredBy);
  form.append("household_id", meta.householdId);
  return submitIngest(baseUrl, { method: "POST", headers: { Accept: "application/json" }, body: form });
}

/**
 * `POST /ingest` as a Drive-picker selection (`application/json`) — the
 * server fetches each picked file's bytes with the stored `drive.file`
 * grant and joins the same pipeline (ADR-023 §1).
 */
export async function startDriveIngest(
  baseUrl: string,
  driveFileIds: readonly string[],
  meta: IngestMeta,
): Promise<IngestSubmitResult> {
  return submitIngest(baseUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      drive_file_ids: driveFileIds,
      idempotency_scope: meta.idempotencyScope,
      triggered_by: meta.triggeredBy,
      household_id: meta.householdId,
    }),
  });
}

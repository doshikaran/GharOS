/**
 * Fetch helpers for the Phase 6 graph HTTP surface
 * (`backend/app/api/graph_router.py`'s four endpoints, minus
 * `/graph/stream` which `lib/graph-stream.ts` owns).
 *
 * Follows `lib/status-checks.ts`'s established pattern: hit a real
 * endpoint, report exactly what happened — a failed call never gets
 * reinterpreted as a fabricated success (gharos-standards, safety
 * invariant #7 in spirit).
 */

import type { GraphSnapshot, JustificationResponse } from "./graph-types";

export class GraphApiError extends Error {
  readonly status: number;
  readonly url: string;

  constructor(message: string, status: number, url: string) {
    super(message);
    this.name = "GraphApiError";
    this.status = status;
    this.url = url;
  }
}

async function fetchJson<T>(url: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new GraphApiError(`Network error reaching ${url}: ${message}`, 0, url);
  }
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new GraphApiError(
      `HTTP ${response.status} ${response.statusText} from ${url}${body ? `, ${body}` : ""}`,
      response.status,
      url,
    );
  }
  return (await response.json()) as T;
}

/** `GET /graph/snapshot` — every current node/edge, once. */
export async function fetchGraphSnapshot(baseUrl: string): Promise<GraphSnapshot> {
  return fetchJson<GraphSnapshot>(`${baseUrl}/graph/snapshot`);
}

/** `GET /graph/nodes/{id}/justification` — the walkable justification chain. */
export async function fetchJustification(baseUrl: string, nodeId: string): Promise<JustificationResponse> {
  return fetchJson<JustificationResponse>(
    `${baseUrl}/graph/nodes/${encodeURIComponent(nodeId)}/justification`,
  );
}

/** URL for `GET /documents/{id}/raw` — used directly as an `<img>` `src`
 * for image-shaped documents; for text-shaped documents, use
 * `fetchDocumentRaw` instead so the bytes can be sliced for highlighting. */
export function documentRawUrl(baseUrl: string, documentId: string): string {
  return `${baseUrl}/documents/${encodeURIComponent(documentId)}/raw`;
}

export interface RawDocumentPayload {
  readonly contentType: string;
  readonly bytes: Uint8Array;
}

/**
 * Fetches a SOURCE_DOCUMENT's raw bytes and real `Content-Type` header
 * (text/* or image/*) — what a node inspector needs to actually render and
 * highlight the provenance region, not just display a region string with
 * nothing to point it at.
 */
export async function fetchDocumentRaw(baseUrl: string, documentId: string): Promise<RawDocumentPayload> {
  const url = documentRawUrl(baseUrl, documentId);
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new GraphApiError(`Network error reaching ${url}: ${message}`, 0, url);
  }
  if (!response.ok) {
    throw new GraphApiError(`HTTP ${response.status} ${response.statusText} from ${url}`, response.status, url);
  }
  const contentType = response.headers.get("content-type") ?? "application/octet-stream";
  const buffer = await response.arrayBuffer();
  return { contentType, bytes: new Uint8Array(buffer) };
}

/**
 * Definitions and runner for the `/status` page's stack-connectivity
 * checks (PHASES.md Phase 2, E4 — "deployed frontend reaching the
 * deployed API", "health/status page showing stack connectivity").
 *
 * Each check hits one real `gharos-api` endpoint and reports exactly what
 * happened — a real 2xx payload, or the real failure detail. Nothing here
 * is allowed to collapse a failure into a generic "something went wrong":
 * this page doubles as a live debug surface (gharos-standards safety
 * invariant #7 in spirit — a failed call never gets reinterpreted as a
 * fabricated success).
 */

export type CheckId = "health" | "gemini-ping" | "adk-demo";

export interface StatusCheckDefinition {
  id: CheckId;
  label: string;
  description: string;
  path: string;
  method: "GET" | "POST";
}

/**
 * The three deployed endpoints Gate 2 requires visible proof of:
 * `/health` (basic reachability), `/debug/gemini-ping` (Requirement 1 —
 * a real Vertex AI Gemini call), `/debug/adk-demo` (Requirement 2 — a
 * real Google ADK agent invoking a real tool). Order matches the order
 * they're introduced in the CTO's brief.
 */
export const STATUS_CHECKS: readonly StatusCheckDefinition[] = [
  {
    id: "health",
    label: "API health",
    description: "Deployed frontend reaches the deployed gharos-api Cloud Run service.",
    path: "/health",
    method: "GET",
  },
  {
    id: "gemini-ping",
    label: "Gemini via Vertex AI",
    description: "A real Gemini call through Vertex AI, made by the deployed backend.",
    path: "/debug/gemini-ping",
    method: "GET",
  },
  {
    id: "adk-demo",
    label: "Google ADK tool invocation",
    description: "A real Google ADK agent invoking a real tool, run by the deployed backend.",
    path: "/debug/adk-demo",
    method: "POST",
  },
] as const;

export type CheckFailureKind = "network" | "timeout" | "http-error" | "invalid-json";

export interface CheckSuccess {
  status: "success";
  httpStatus: number;
  data: unknown;
  durationMs: number;
}

export interface CheckFailure {
  status: "failure";
  kind: CheckFailureKind;
  message: string;
  httpStatus?: number;
  body?: unknown;
  durationMs: number;
}

export type CheckOutcome = CheckSuccess | CheckFailure;

const TIMEOUT_MS = 10_000;

/**
 * Runs one status check against a real HTTP endpoint and reports exactly
 * what happened.
 *
 * Distinguishes the three real failure modes the CTO's brief calls out
 * explicitly rather than folding them into one generic error: a network
 * error (DNS/connection/CORS failure — `fetch` itself rejects), a
 * request timeout (aborted after `TIMEOUT_MS`), and a non-2xx HTTP
 * response (the server answered, but with an error). A 2xx response
 * whose body isn't valid JSON is also reported distinctly rather than
 * silently treated as an empty success.
 *
 * @param definition - which endpoint/method to call.
 * @param baseUrl - the API's base URL (see `getApiBaseUrl`), no trailing slash required.
 * @returns The real outcome — a typed success with the parsed payload, or a typed failure with the real error detail.
 */
export async function runStatusCheck(
  definition: StatusCheckDefinition,
  baseUrl: string,
): Promise<CheckOutcome> {
  const url = `${baseUrl}${definition.path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const startedAt = Date.now();

  try {
    const response = await fetch(url, {
      method: definition.method,
      signal: controller.signal,
    });
    const durationMs = Date.now() - startedAt;
    const rawText = await response.text();

    let parsed: unknown = null;
    let parseFailed = false;
    if (rawText.length > 0) {
      try {
        parsed = JSON.parse(rawText);
      } catch {
        parseFailed = true;
      }
    }

    if (!response.ok) {
      return {
        status: "failure",
        kind: "http-error",
        message: `HTTP ${response.status} ${response.statusText}`,
        httpStatus: response.status,
        body: parseFailed ? rawText : parsed,
        durationMs,
      };
    }

    if (parseFailed) {
      return {
        status: "failure",
        kind: "invalid-json",
        message: "Server responded 2xx but the body was not valid JSON.",
        httpStatus: response.status,
        body: rawText,
        durationMs,
      };
    }

    return { status: "success", httpStatus: response.status, data: parsed, durationMs };
  } catch (err) {
    const durationMs = Date.now() - startedAt;
    if (err instanceof DOMException && err.name === "AbortError") {
      return {
        status: "failure",
        kind: "timeout",
        message: `Request timed out after ${TIMEOUT_MS}ms with no response.`,
        durationMs,
      };
    }
    const message = err instanceof Error ? err.message : String(err);
    return { status: "failure", kind: "network", message, durationMs };
  } finally {
    clearTimeout(timeoutId);
  }
}

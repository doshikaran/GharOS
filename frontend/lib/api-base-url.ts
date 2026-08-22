const DEFAULT_API_BASE_URL = "http://localhost:8000";

/**
 * Resolves the GharOS API's base URL for client-side fetches.
 *
 * Configured via `NEXT_PUBLIC_API_BASE_URL`, a standard Next.js
 * build-time-inlined public env var (PHASES.md Phase 2, E4 work item —
 * "deployed frontend reaching the deployed API"). Deliberately never
 * hardcodes the deployed Cloud Run URL: that value is deploy-time
 * configuration the operator supplies when building `gharos-web`, not a
 * compile-time constant that belongs in committed source.
 *
 * Falls back to the local dev API address when unset, so `pnpm dev` works
 * against a locally-running `gharos-api` with zero configuration.
 *
 * @returns The API base URL with any trailing slash stripped.
 */
export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  const value = configured && configured.trim().length > 0 ? configured.trim() : DEFAULT_API_BASE_URL;
  return value.replace(/\/+$/, "");
}

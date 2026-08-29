# ADR-022: OAuth in a backend-only architecture — Authorization Code + PKCE, refresh tokens in Secret Manager, Google restricted scopes in test mode

**Status:** accepted
**Phase:** 14.5
**Date:** 2026-08-29

## Context

Phase 14.5 turns ingestion from "parsers that exist but nothing calls" into a path a household member triggers: "scan my Gmail and Outlook", reading the last 24 hours through official OAuth APIs. GharOS is a deployed web app (Cloud Run `gharos-api` + `gharos-web`), single-tenant, with no native desktop companion. That constrains what a connector can legitimately reach and how it must authenticate:

- **Gmail:** `https://www.googleapis.com/auth/gmail.readonly` — a Google **restricted** scope (requires a CASA security assessment + brand verification for production use by >100 users).
- **Google Drive picker:** `https://www.googleapis.com/auth/drive.file` — a **non-sensitive**, per-file scope granted by the Google Picker; needs no verification.
- **Outlook:** Microsoft Graph `Mail.Read` (delegated) — granted by ordinary user consent; no admin consent, no verification programme for a low-volume app.

There is no service account / domain-wide-delegation path here (that is Google Workspace admin territory, and it would read as the excluded "Fortified Enterprise Fleet" shape — see PHASES.md track discipline). Every fetch is **delegated user authorization**: a specific person clicks "connect", consents, and the household's backend holds a refresh token for that person's mailbox.

The refresh token is a long-lived credential. Spec §23 ("financial credentials never touch a reasoning agent") states the principle that applies to every credential in this system: nothing a reasoning agent can reach may carry token material.

## Decision

### 1. Authorization Code flow with PKCE, consent-start and callback as FastAPI routes

Two new routes on `gharos-api` (E3, `backend/app/api/oauth_router.py`):

- **`GET /oauth/{provider}/start`** — builds the provider's authorization URL and 302-redirects the browser to it. Query/state described below. `provider ∈ {google, microsoft}`.
- **`GET /oauth/{provider}/callback`** — the provider redirects back here with `?code=...&state=...`. The route validates `state`, exchanges the code (+ PKCE `code_verifier`) for tokens, stores the refresh token in Secret Manager, writes an `OAuthCredential` record, and redirects the browser to the frontend Connections surface with a success/failure marker.

PKCE (`code_challenge_method=S256`) is used for **both** providers even though the backend can hold a client secret, because:

- It removes any dependence on the client secret for the code-exchange leg, so a leaked-secret scenario does not by itself allow code interception.
- Microsoft Graph's "SPA"/public-client guidance and Google's current guidance both recommend PKCE for authorization-code flows regardless of client type.
- The `code_verifier` is generated per flow and held server-side keyed by `state` (see §3) — it never reaches the browser, so this is confidential-client + PKCE, the strongest of the available combinations.

The OAuth **client type is "web application"** for both providers (a real confidential client with a secret, secret stored in Secret Manager, read at startup). The redirect URIs are the deployed `gharos-api` callback URLs plus `http://localhost:8000/oauth/{provider}/callback` for local development.

### 2. Refresh token in Secret Manager, keyed by principal; only the resource name persisted

On a successful code exchange the callback route:

1. Extracts `refresh_token`, `scope` (granted scopes), and the account identity (`email` for Google via the id_token / userinfo; `userPrincipalName` for Microsoft via `/me`).
2. Writes the refresh token to Secret Manager as secret id
   `gharos-oauth-refresh--{provider}--{principal-slug}` (principal lowercased, `@`/`.` → `-`), creating the secret if absent and adding a new version if it exists. **Payload is the raw refresh token, nothing else.**
3. Writes an `OAuthCredential` (`contracts.ingestion`) via `OAuthCredentialStore.put` (E1, Firestore `oauth_credentials`) carrying `provider`, `principal`, `granted_scopes`, `secret_ref` (the full `projects/.../secrets/.../versions/latest` resource name), `connected_at`. **No token, no code, no client secret in this record. Ever.**

Access tokens are obtained inside a connector, at run time, by:
`OAuthCredentialStore.get(provider, principal)` → read `secret_ref` → `SecretManagerAdapter.get_secret(...)` → exchange refresh token at the provider's token endpoint → hold the access token in a local variable for the duration of `fetch_since`. It is never written to Firestore, never logged, never placed on an `AgentInput`, never returned from the connector. `backend/app/agents/` holds no import path to `app.adapters.secret_manager` or to the connectors — the same structural isolation used for gated tools.

### 3. CSRF / `state` handling

`GET /oauth/{provider}/start` generates:

- `state` — 32 bytes URL-safe random.
- `code_verifier` — 64 bytes URL-safe random; `code_challenge = BASE64URL(SHA256(code_verifier))`.

Both, plus the intended `principal` hint and a short TTL (10 minutes), are stored server-side in a `oauth_pending` Firestore collection (E1) keyed by `state`. The browser only ever carries `state`. `GET /oauth/{provider}/callback`:

- rejects a missing/unknown/expired `state` with `400` (a real rejection — never a fabricated success, invariant #7);
- deletes the `oauth_pending` entry on use (single-use);
- validates the `iss`/`aud` of Google's returned `id_token`, and for Microsoft validates the token endpoint response shape, before trusting the principal.

No cookies are used for OAuth state — the `state`→server-record indirection is the CSRF defence, and it works identically for the localhost and deployed redirect URIs.

### 4. Token refresh and expiry

- Each `fetch_since` exchanges the refresh token for a fresh access token; access tokens are not cached across runs (a run is short, and caching would mean persisting them).
- A `400 invalid_grant` (Google) / `AADSTS700082` or `invalid_grant` (Microsoft) on the exchange → `contracts.errors.OAuthTokenRefreshFailed`, surfaced as `ConnectorFailure(is_auth_failure=True)` → the Connections UI shows "reconnect needed".
- **Google restricted scopes (`gmail.readonly`) run in OAuth test mode for the demo.** In test mode Google issues refresh tokens that **expire after 7 days**. This is a real, documented limitation, stated plainly in the submission write-up (PHASES.md Phase 14.5 out-of-scope note + this ADR): the demo connects a named test account within the 7-day window; a production deployment would require Google's restricted-scope verification (CASA assessment), which is out of scope for the hackathon. `drive.file` and Microsoft `Mail.Read` have no such 7-day limit.

### 5. Revocation / disconnect

`POST /connections/{provider}/{principal}/disconnect` (E3):

1. Best-effort calls the provider's token-revocation endpoint (Google `https://oauth2.googleapis.com/revoke`; Microsoft has no delegated programmatic revoke — the record is marked revoked and the user is pointed at their Microsoft account's app-permissions page).
2. `OAuthCredentialStore.mark_revoked(provider, principal, revoked_at=now)` — a soft delete (`revoked_at` set once, never cleared; matches the project's supersession discipline).
3. Destroys the Secret Manager secret version(s) for that `secret_ref` (`secrets versions destroy`).

A revoked record is retained for the audit trail; `list_active` filters it out and the UI shows it as "disconnected on <date>".

### 6. Scopes requested (least privilege)

| Provider | Scopes | Verification |
|---|---|---|
| Google (Gmail) | `openid email` + `gmail.readonly` | restricted — **test mode for the demo** |
| Google (Drive picker) | `openid email` + `drive.file` | none needed |
| Microsoft | `openid email offline_access` + `Mail.Read` | ordinary user consent |

`gmail.readonly` and `drive.file` may be requested in one Google consent (one `OAuthCredential` with both), or separately — `granted_scopes` records what was actually granted and a connector raises `OAuthScopeInsufficient` on a shortfall rather than degrading.

## Alternatives considered

1. **Device Authorization Grant (device code flow).** Rejected: it exists for input-constrained devices, and while it would avoid a redirect URI, it produces a worse demo (the user copies a code to another screen) and still yields the same refresh-token-at-rest problem. The redirect flow is the honest, standard shape for a web app.
2. **Store the refresh token encrypted in Firestore (app-level envelope encryption) instead of Secret Manager.** Rejected: it puts ciphertext of a live credential next to graph data a reasoning agent's `GraphReader` can reach, and the KMS key handling reinvents what Secret Manager already provides with IAM-scoped access and audit logging. Secret Manager keeps the credential on a completely separate access path from the graph.
3. **Ask the user to paste an app password / their own OAuth token.** Rejected: Gmail app passwords require 2FA and only work for IMAP/SMTP (a different, messier integration), and pasting a token trains exactly the phishing-shaped behaviour a household assistant should not normalise.
4. **Pursue Google restricted-scope verification for the submission.** Rejected: the CASA assessment turnaround is measured in weeks and cost, well outside the submission window. Test mode with a stated 7-day limitation is the honest, achievable path; the write-up says so rather than implying a verified integration.

## Consequences

- **New files (E3):** `backend/app/api/oauth_router.py` (the 4 routes), `backend/app/adapters/oauth/` (provider token-exchange clients — `google.py`, `microsoft.py`; plain `httpx`/`requests`-level code, no heavyweight OAuth library required). `backend/app/main.py` gains `app.include_router(oauth_router)` (E3 owns `main.py`? no — E3 raises the one-line include to the CTO if `main.py` ownership is contested; in practice `main.py` edits for router registration have been made by the router's owner each phase — voice_router by E3 — so E3 makes this one, consistent with precedent).
- **New files (E1):** `backend/app/persistence/oauth_credential_store.py` (`oauth_credentials` collection), `oauth_pending` handling (may live in the same module). Both implement `contracts.ingestion` Protocols.
- **New settings (`backend/app/settings.py`, E3-owned via CTO for root config? — `settings.py` is under `backend/app/`, E3's tree):** `google_oauth_client_id`, `google_oauth_client_secret_ref`, `microsoft_oauth_client_id`, `microsoft_oauth_client_secret_ref`, `microsoft_oauth_tenant` (`consumers` or `common`), `oauth_redirect_base_url`. Client **secrets** are themselves Secret Manager ids, read at startup — never in `.env` committed anywhere.
- **Operator prerequisites** (enumerated for the Phase 14.5 dispatch): a Google Cloud OAuth 2.0 **Web application** client (client id + secret, redirect URIs registered) with the OAuth consent screen configured, `gmail.readonly` + `drive.file` added, publishing status **Testing**, and the demo Gmail account added as a **Test user**; an Azure **app registration** (single-tenant `consumers` or multi-tenant `common`) with a Web redirect URI, a client secret, and `Mail.Read` + `offline_access` delegated permissions; both client secrets loaded into Secret Manager. The demo must be recorded within 7 days of connecting the Google account.
- **Honesty debts carried into the write-up:** Gmail runs in OAuth test mode (7-day refresh token, <100 users) — a real limitation, not implied away. No local-filesystem / Apple Photos / iMessage / WhatsApp read is possible from a deployed web app; that is a post-submission native-companion roadmap item, stated as such.
- Invariant #7 (no fabricated success) extends to this surface: a failed `state` check, a failed code exchange, a failed token refresh each produce a real error response / `ConnectorFailure`, never a silent "connected".

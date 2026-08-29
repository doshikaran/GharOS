"""GharOS — the OAuth *consent handshake* for ingestion connectors
(Phase 14.5, ADR-022). E3's own router, registered in `app.main` next to
`app.api.voice_router` / `app.api.ingest_router` following the same
pattern.

Routes here (the handshake only — the connection-management surface,
`GET /connections` and the disconnect route, lives in
`app.api.ingest_router`, which E4's Connections page talks to):

- `GET /oauth/{provider}/start` — generate `state` + PKCE `code_verifier`,
  persist them in the `oauth_pending` store (E1), 302 the browser to the
  provider consent screen.
- `GET /oauth/{provider}/callback` — validate `state` (single-use,
  TTL-checked by `OAuthPendingStore.take_pending`), exchange the code,
  write the refresh token to Secret Manager, write the `OAuthCredential`
  reference record (E1), 302 back to the frontend Connections page with a
  success/failure marker.
- `GET /oauth/google/picker-token` — mint a short-lived `drive.file`
  access token for the browser Google Picker widget only, from the stored
  Google refresh token for a connected principal (ADR-022 follow-up; the
  Picker is a browser component that genuinely needs a browser-held
  token, and `drive.file` is a non-sensitive per-file scope).

Invariant #7 reaches this surface: a bad `state`, a failed exchange, a
failed token write each produce a real error response / failure marker,
never a fabricated "connected". The persisted `OAuthCredential` never
carries token material — only a Secret Manager `secret_ref` pointer
(spec §23, ADR-022 §2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

import structlog
from contracts.ingestion import OAuthCredential, OAuthProvider
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.adapters.oauth import GoogleOAuthClient, MicrosoftOAuthClient, OAuthExchangeFailed
from app.adapters.oauth.base import OAuthClient
from app.adapters.oauth.google import DRIVE_FILE_SCOPE
from app.adapters.oauth.pkce import generate_pkce_pair, generate_state
from app.adapters.secret_manager import (
    SecretManagerAdapter,
    SecretManagerError,
    SecretManagerWriteAdapter,
)
from app.persistence.firestore_client import create_firestore_client
from app.persistence.oauth_credential_store import (
    FirestoreOAuthCredentialStore,
    create_oauth_credential_store,
)
from app.persistence.oauth_pending_store import (
    FirestoreOAuthPendingStore,
    create_oauth_pending_store,
)
from app.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["oauth"])

_PROVIDER_BY_SLUG = {"google": OAuthProvider.GOOGLE, "microsoft": OAuthProvider.MICROSOFT}
_REFRESH_SECRET_PREFIX = "gharos-oauth-refresh"


# ---------------------------------------------------------------------------
# Dependency providers — per-request, no module-level singletons. Shared
# with `app.api.ingest_router`, which imports the credential-store /
# secret-adapter providers from here so there is one composition root for
# the OAuth surface.
# ---------------------------------------------------------------------------


def get_secret_reader(settings: Annotated[Settings, Depends(get_settings)]) -> SecretManagerAdapter:
    return SecretManagerAdapter.from_settings(settings)


def get_secret_writer(settings: Annotated[Settings, Depends(get_settings)]) -> SecretManagerWriteAdapter:
    return SecretManagerWriteAdapter.from_settings(settings)


def get_pending_store() -> FirestoreOAuthPendingStore:
    return create_oauth_pending_store(create_firestore_client(get_settings()))


def get_credential_store() -> FirestoreOAuthCredentialStore:
    return create_oauth_credential_store(create_firestore_client(get_settings()))


def _resolve_client_secret(reader: SecretManagerAdapter, secret_ref: str, provider: str) -> str:
    if not secret_ref:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider} OAuth is not configured (no client secret ref set)",
        )
    try:
        return reader.get_secret(secret_ref)
    except SecretManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider} OAuth client secret could not be read: {exc}",
        ) from exc


def get_oauth_client_for(
    provider_slug: str,
    settings: Settings,
    reader: SecretManagerAdapter,
) -> OAuthClient:
    """Builds the provider's OAuth client with its client id (plain
    config) and client secret (itself a Secret Manager id, read here).
    Called manually inside the routes, not via `Depends`, because the
    provider is a path parameter."""
    if provider_slug == "google":
        if not settings.google_oauth_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google OAuth is not configured"
            )
        secret = _resolve_client_secret(reader, settings.google_oauth_client_secret_ref, "Google")
        return GoogleOAuthClient(
            client_id=settings.google_oauth_client_id,
            client_secret=secret,
            redirect_uri=settings.google_oauth_redirect_uri,
        )
    if provider_slug == "microsoft":
        if not settings.microsoft_oauth_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft OAuth is not configured"
            )
        secret = _resolve_client_secret(reader, settings.microsoft_oauth_client_secret_ref, "Microsoft")
        return MicrosoftOAuthClient(
            client_id=settings.microsoft_oauth_client_id,
            client_secret=secret,
            redirect_uri=settings.microsoft_oauth_redirect_uri,
            tenant=settings.microsoft_oauth_tenant,
        )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown provider {provider_slug!r}")


def provider_or_404(provider_slug: str) -> OAuthProvider:
    provider = _PROVIDER_BY_SLUG.get(provider_slug)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown provider {provider_slug!r}"
        )
    return provider


def refresh_secret_id(provider: OAuthProvider, principal: str) -> str:
    slug = principal.lower().replace("@", "-").replace(".", "-")
    return f"{_REFRESH_SECRET_PREFIX}--{provider.value}--{slug}"


def secret_id_from_ref(secret_ref: str) -> str:
    if "/secrets/" not in secret_ref:
        return secret_ref
    tail = secret_ref.split("/secrets/", 1)[1]
    return tail.split("/versions/", 1)[0]


# ---------------------------------------------------------------------------
# GET /oauth/{provider}/start
# ---------------------------------------------------------------------------


@router.get("/oauth/{provider}/start")
def oauth_start(
    provider: str,
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    pending_store: Annotated[FirestoreOAuthPendingStore, Depends(get_pending_store)],
    principal_hint: Annotated[str, Query()] = "",
) -> RedirectResponse:
    oauth_provider = provider_or_404(provider)
    client = get_oauth_client_for(provider, settings, reader)
    state = generate_state()
    pkce = generate_pkce_pair()
    # `state` -> {code_verifier, principal_hint} is held server-side only;
    # the browser carries just `state` (ADR-022 §3). The provider for this
    # flow is fixed by the callback URL path, not stored here.
    pending_store.put_pending(state, code_verifier=pkce.verifier, principal_hint=principal_hint or None)
    authorization_url = client.build_authorization_url(state=state, code_challenge=pkce.challenge)
    logger.info("oauth.start", provider=oauth_provider.value, principal_hint=principal_hint or None)
    return RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# GET /oauth/{provider}/callback
# ---------------------------------------------------------------------------


def _connections_redirect(settings: Settings, **markers: str) -> RedirectResponse:
    base = settings.frontend_connections_url
    sep = "&" if "?" in base else "?"
    return RedirectResponse(f"{base}{sep}{urlencode(markers)}", status_code=status.HTTP_302_FOUND)


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    secret_writer: Annotated[SecretManagerWriteAdapter, Depends(get_secret_writer)],
    pending_store: Annotated[FirestoreOAuthPendingStore, Depends(get_pending_store)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    error: Annotated[str, Query()] = "",
) -> RedirectResponse:
    oauth_provider = provider_or_404(provider)

    if error:
        logger.warning("oauth.callback.provider_error", provider=oauth_provider.value, error=error)
        return _connections_redirect(settings, connect="denied", provider=oauth_provider.value, reason=error)

    # A bad/missing/expired `state` is a real rejection (invariant #7,
    # ADR-022 §3) — a 400, never a redirect that could be forged.
    if not state or not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing `state` or `code`")
    pending = pending_store.take_pending(state)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="unknown, expired, or already-used `state`"
        )

    client = get_oauth_client_for(provider, settings, reader)
    try:
        tokens = client.exchange_code(code=code, code_verifier=pending.code_verifier)
    except OAuthExchangeFailed as exc:
        logger.warning("oauth.callback.exchange_failed", provider=oauth_provider.value, reason=exc.reason)
        return _connections_redirect(
            settings, connect="error", provider=oauth_provider.value, reason=exc.reason[:200]
        )

    if pending.principal_hint and pending.principal_hint.lower() != tokens.principal.lower():
        # The verified id_token / `/me` identity is authoritative; a
        # mismatch with the UI's hint is logged, not fatal (the user may
        # have picked a different account on the consent screen).
        logger.info(
            "oauth.callback.principal_hint_mismatch",
            provider=oauth_provider.value,
            hint=pending.principal_hint,
            actual=tokens.principal,
        )

    secret_id = refresh_secret_id(oauth_provider, tokens.principal)
    try:
        secret_ref = secret_writer.put_secret(secret_id, tokens.refresh_token)
    except SecretManagerError as exc:
        logger.error("oauth.callback.secret_write_failed", provider=oauth_provider.value, error=str(exc))
        return _connections_redirect(
            settings,
            connect="error",
            provider=oauth_provider.value,
            reason="could not store the refresh token",
        )

    credential_store.put(
        OAuthCredential(
            provider=oauth_provider,
            principal=tokens.principal,
            granted_scopes=tokens.granted_scopes,
            secret_ref=secret_ref,
            connected_at=datetime.now(UTC),
        )
    )
    logger.info(
        "oauth.callback.connected",
        provider=oauth_provider.value,
        principal=tokens.principal,
        granted_scopes=list(tokens.granted_scopes),
    )
    return _connections_redirect(
        settings, connect="ok", provider=oauth_provider.value, principal=tokens.principal
    )


# ---------------------------------------------------------------------------
# GET /oauth/google/picker-token
# ---------------------------------------------------------------------------


@router.get("/oauth/google/picker-token")
def google_picker_token(
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
    principal: Annotated[str, Query()] = "",
) -> JSONResponse:
    """Mints a short-lived `drive.file` access token for the browser
    Google Picker widget (ADR-022 follow-up). This is the one place a
    token value is handed to the browser, and only for `drive.file` — a
    non-sensitive, per-file scope. Never returns a refresh token; never
    persists the minted access token."""
    if not principal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="`principal` is required")
    credential = credential_store.get(OAuthProvider.GOOGLE, principal)
    if credential is None or not credential.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no connected Google account for {principal!r}"
        )
    if DRIVE_FILE_SCOPE not in credential.granted_scopes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"the Google grant for {principal!r} does not include the Drive picker scope",
        )
    try:
        refresh_token = reader.get_secret_by_resource_name(credential.secret_ref)
    except SecretManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"could not read the stored Google refresh token: {exc}",
        ) from exc
    client = get_oauth_client_for("google", settings, reader)
    try:
        refreshed = client.refresh_access_token(refresh_token)
    except OAuthExchangeFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token refresh failed (reconnect the account): {exc.reason}",
        ) from exc
    return JSONResponse({"access_token": refreshed.access_token, "expires_in": refreshed.expires_in})


__all__ = [
    "get_credential_store",
    "get_oauth_client_for",
    "get_pending_store",
    "get_secret_reader",
    "get_secret_writer",
    "provider_or_404",
    "refresh_secret_id",
    "router",
    "secret_id_from_ref",
]

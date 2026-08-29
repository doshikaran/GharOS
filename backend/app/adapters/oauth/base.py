"""Shared shapes and HTTP plumbing for the OAuth clients (ADR-022).

The `httpx` round trips are funnelled through `post_form` so every client
gets the same timeout, the same JSON/`application/x-www-form-urlencoded`
error handling, and the same injectable `httpx.BaseTransport` seam that
lets `tests/test_oauth_clients.py` drive them with `httpx.MockTransport`
and zero network access.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Protocol

import httpx
from contracts.ingestion import OAuthProvider

from .errors import OAuthExchangeFailed

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
"""One place for the token-endpoint timeout — a consent exchange or a
per-run refresh should never hang a request handler or a scan."""

_INVALID_GRANT_MARKERS = ("invalid_grant", "aadsts700082", "aadsts50173", "aadsts50076", "aadsts900144")


@dataclass(frozen=True, slots=True)
class ExchangedTokens:
    """The full result of a successful authorization-code exchange — what
    the OAuth callback route needs to persist a connection.

    `refresh_token` goes to Secret Manager; `granted_scopes` + `principal`
    go onto the `OAuthCredential` record; `access_token` is discarded by
    the route (it is re-minted per run from the refresh token) except that
    the Microsoft client uses it once, in-process, to read `/me` for the
    principal.
    """

    refresh_token: str
    access_token: str
    expires_in: int
    granted_scopes: tuple[str, ...]
    principal: str


@dataclass(frozen=True, slots=True)
class RefreshedToken:
    """A fresh access token minted from a stored refresh token, held in
    memory for one `fetch_since` and never persisted."""

    access_token: str
    expires_in: int


class OAuthClient(Protocol):
    """The provider-agnostic interface `oauth_router` and the connectors
    depend on. `GoogleOAuthClient` / `MicrosoftOAuthClient` implement it
    with plain `httpx`."""

    provider: OAuthProvider

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        """The provider consent URL to 302 the browser to (S256 PKCE,
        offline access so a refresh token is issued)."""
        ...

    def exchange_code(self, *, code: str, code_verifier: str) -> ExchangedTokens:
        """Exchange an authorization `code` (+ the PKCE `code_verifier`)
        for tokens, granted scopes, and the resolved account principal.

        Raises:
            OAuthExchangeFailed: the token endpoint rejected the exchange
                or returned an unusable response.
            OAuthPrincipalUnresolved: tokens were issued but the account
                identity could not be established.
        """
        ...

    def refresh_access_token(self, refresh_token: str) -> RefreshedToken:
        """Exchange a stored refresh token for a fresh access token.

        Raises:
            OAuthExchangeFailed: the refresh failed. `invalid_grant=True`
                means the grant is gone (revoked / expired) and the user
                must reconnect.
        """
        ...


def _looks_like_invalid_grant(payload: dict[str, object], body_text: str) -> bool:
    error = str(payload.get("error", "")).lower()
    description = str(payload.get("error_description", "")).lower()
    haystack = f"{error} {description} {body_text.lower()}"
    return any(marker in haystack for marker in _INVALID_GRANT_MARKERS)


def post_form(
    url: str,
    data: dict[str, str],
    *,
    provider: OAuthProvider,
    stage: str,
    transport: httpx.BaseTransport | None,
) -> dict[str, object]:
    """POST an `application/x-www-form-urlencoded` body to a token
    endpoint and return the parsed JSON object.

    Raises `OAuthExchangeFailed` on any transport error, any non-2xx
    response, or a body that is not a JSON object — with `invalid_grant`
    set when the provider's error payload says so.
    """
    try:
        with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                url,
                data=data,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise OAuthExchangeFailed(
            provider=provider.value, stage=stage, reason=f"transport error: {exc}", invalid_grant=False
        ) from exc

    body_text = response.text
    try:
        parsed = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        parsed = {}

    if not isinstance(parsed, dict):
        raise OAuthExchangeFailed(
            provider=provider.value,
            stage=stage,
            reason=f"HTTP {response.status_code}: token endpoint returned a non-object body",
            invalid_grant=False,
        )

    if response.is_success:
        return parsed

    raise OAuthExchangeFailed(
        provider=provider.value,
        stage=stage,
        reason=f"HTTP {response.status_code}: {parsed.get('error', body_text[:200] or 'no body')}",
        invalid_grant=_looks_like_invalid_grant(parsed, body_text),
    )


def get_json(
    url: str,
    *,
    access_token: str,
    provider: OAuthProvider,
    stage: str,
    transport: httpx.BaseTransport | None,
) -> dict[str, object]:
    """Authenticated GET returning a JSON object (used only for the
    Microsoft `/me` principal lookup — Gmail/Graph message fetching lives
    in the connectors, with their own retry/backoff)."""
    try:
        with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as exc:
        raise OAuthExchangeFailed(
            provider=provider.value, stage=stage, reason=f"transport error: {exc}", invalid_grant=False
        ) from exc
    if not response.is_success:
        raise OAuthExchangeFailed(
            provider=provider.value,
            stage=stage,
            reason=f"HTTP {response.status_code}: {response.text[:200]}",
            invalid_grant=False,
        )
    parsed = response.json()
    if not isinstance(parsed, dict):
        raise OAuthExchangeFailed(
            provider=provider.value, stage=stage, reason="expected a JSON object", invalid_grant=False
        )
    return parsed


def decode_jwt_payload(token: str) -> dict[str, object]:
    """Decode (NOT signature-verify) a JWT's payload segment.

    The `id_token` is read straight from the provider's token-endpoint
    response over TLS, so ADR-022 §3's requirement is to validate `iss` /
    `aud` — done by the caller — not to re-verify a signature on a token
    the authorization server just handed us directly. Returns `{}` for a
    structurally unusable token; the caller treats a missing `email` /
    bad `iss` as `OAuthPrincipalUnresolved`.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
        parsed = json.loads(raw)
    except (binascii.Error, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_scopes(raw_scope: object) -> tuple[str, ...]:
    """Normalise a token response's `scope` (a space-separated string per
    RFC 6749, occasionally a list) into a tuple."""
    if isinstance(raw_scope, str):
        return tuple(s for s in raw_scope.split(" ") if s)
    if isinstance(raw_scope, list):
        return tuple(str(s) for s in raw_scope if s)
    return ()


def coerce_expires_in(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


__all__ = [
    "HTTP_TIMEOUT",
    "ExchangedTokens",
    "OAuthClient",
    "RefreshedToken",
    "coerce_expires_in",
    "decode_jwt_payload",
    "get_json",
    "parse_scopes",
    "post_form",
]

"""Google OAuth 2.0 Authorization-Code + PKCE client (ADR-022 §1, §6).

Scopes: `openid email` (to identify the account) plus the ingestion
scopes — `gmail.readonly` (a Google *restricted* scope, run in OAuth
**test mode** for the demo: a 7-day refresh token, ADR-022 §4) and
`drive.file` (non-sensitive, per-file, granted alongside so the
Drive-picker fetch helper can read a user-picked file with the same
grant). `access_type=offline` + `prompt=consent` so a refresh token is
always issued.

The account principal is the `email` claim of the `id_token` returned by
the token endpoint, accepted only after its `iss` and `aud` check out
(ADR-022 §3).
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from contracts.ingestion import OAuthProvider

from .base import (
    ExchangedTokens,
    RefreshedToken,
    coerce_expires_in,
    decode_jwt_payload,
    parse_scopes,
    post_form,
)
from .errors import OAuthExchangeFailed, OAuthPrincipalUnresolved

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_DEFAULT_SCOPES: tuple[str, ...] = ("openid", "email", GMAIL_READONLY_SCOPE, DRIVE_FILE_SCOPE)

_VALID_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})


class GoogleOAuthClient:
    """`OAuthClient` for Google. Confidential web client (client id +
    secret) *and* PKCE — the strongest combination (ADR-022 §1)."""

    provider = OAuthProvider.GOOGLE

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: tuple[str, ...] = _DEFAULT_SCOPES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._transport = transport

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        return f"{_AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, *, code: str, code_verifier: str) -> ExchangedTokens:
        payload = post_form(
            _TOKEN_ENDPOINT,
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            provider=self.provider,
            stage="code-exchange",
            transport=self._transport,
        )
        refresh_token = str(payload.get("refresh_token") or "")
        access_token = str(payload.get("access_token") or "")
        if not refresh_token:
            raise OAuthExchangeFailed(
                provider=self.provider.value,
                stage="code-exchange",
                reason="token response carried no refresh_token (was access_type=offline honoured?)",
                invalid_grant=False,
            )
        principal = self._principal_from_id_token(str(payload.get("id_token") or ""))
        return ExchangedTokens(
            refresh_token=refresh_token,
            access_token=access_token,
            expires_in=coerce_expires_in(payload.get("expires_in")),
            granted_scopes=parse_scopes(payload.get("scope")),
            principal=principal,
        )

    def refresh_access_token(self, refresh_token: str) -> RefreshedToken:
        payload = post_form(
            _TOKEN_ENDPOINT,
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            provider=self.provider,
            stage="token-refresh",
            transport=self._transport,
        )
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise OAuthExchangeFailed(
                provider=self.provider.value,
                stage="token-refresh",
                reason="refresh response carried no access_token",
                invalid_grant=False,
            )
        return RefreshedToken(
            access_token=access_token, expires_in=coerce_expires_in(payload.get("expires_in"))
        )

    def _principal_from_id_token(self, id_token: str) -> str:
        claims = decode_jwt_payload(id_token)
        issuer = str(claims.get("iss", ""))
        audience = str(claims.get("aud", ""))
        email = str(claims.get("email", ""))
        if issuer not in _VALID_ISSUERS:
            raise OAuthPrincipalUnresolved(
                provider=self.provider.value, reason=f"id_token has unexpected iss {issuer!r}"
            )
        if audience != self._client_id:
            raise OAuthPrincipalUnresolved(
                provider=self.provider.value, reason="id_token aud does not match this client id"
            )
        if not email:
            raise OAuthPrincipalUnresolved(
                provider=self.provider.value, reason="id_token carried no email claim"
            )
        return email.lower()


__all__ = [
    "DRIVE_FILE_SCOPE",
    "GMAIL_READONLY_SCOPE",
    "REVOKE_ENDPOINT",
    "GoogleOAuthClient",
]

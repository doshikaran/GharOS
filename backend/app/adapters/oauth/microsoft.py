"""Microsoft identity platform (v2.0) OAuth Authorization-Code + PKCE
client (ADR-022 §1, §6).

Scopes: `openid email offline_access` plus `https://graph.microsoft.com/
Mail.Read` (delegated, ordinary user consent — no admin consent, no
verification programme for a low-volume app). `offline_access` is what
makes the token endpoint return a refresh token. Microsoft refresh tokens
have no 7-day test-mode limit.

The account principal is `userPrincipalName` read from
`GET https://graph.microsoft.com/v1.0/me` with the freshly-issued access
token (ADR-022 §2) — Microsoft's `id_token` does not always carry a UPN
claim, so `/me` is the reliable source.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from contracts.ingestion import OAuthProvider

from .base import (
    ExchangedTokens,
    RefreshedToken,
    coerce_expires_in,
    get_json,
    parse_scopes,
    post_form,
)
from .errors import OAuthExchangeFailed, OAuthPrincipalUnresolved

_AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/{leg}"
_ME_ENDPOINT = "https://graph.microsoft.com/v1.0/me"

MAIL_READ_SCOPE = "https://graph.microsoft.com/Mail.Read"
_DEFAULT_SCOPES: tuple[str, ...] = ("openid", "email", "offline_access", MAIL_READ_SCOPE)


class MicrosoftOAuthClient:
    """`OAuthClient` for Microsoft Graph mail. Confidential web client +
    PKCE (ADR-022 §1)."""

    provider = OAuthProvider.MICROSOFT

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        tenant: str = "consumers",
        scopes: tuple[str, ...] = _DEFAULT_SCOPES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._tenant = tenant or "consumers"
        self._scopes = scopes
        self._transport = transport

    def _authority(self, leg: str) -> str:
        return _AUTHORITY_TEMPLATE.format(tenant=self._tenant, leg=leg)

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "response_mode": "query",
            "scope": " ".join(self._scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{self._authority('authorize')}?{urlencode(params)}"

    def exchange_code(self, *, code: str, code_verifier: str) -> ExchangedTokens:
        payload = post_form(
            self._authority("token"),
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "scope": " ".join(self._scopes),
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
                reason="token response carried no refresh_token (was offline_access requested?)",
                invalid_grant=False,
            )
        if not access_token:
            raise OAuthExchangeFailed(
                provider=self.provider.value,
                stage="code-exchange",
                reason="token response carried no access_token",
                invalid_grant=False,
            )
        principal = self._principal_from_me(access_token)
        return ExchangedTokens(
            refresh_token=refresh_token,
            access_token=access_token,
            expires_in=coerce_expires_in(payload.get("expires_in")),
            granted_scopes=parse_scopes(payload.get("scope")),
            principal=principal,
        )

    def refresh_access_token(self, refresh_token: str) -> RefreshedToken:
        payload = post_form(
            self._authority("token"),
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(self._scopes),
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

    def _principal_from_me(self, access_token: str) -> str:
        me = get_json(
            _ME_ENDPOINT,
            access_token=access_token,
            provider=self.provider,
            stage="principal-resolution",
            transport=self._transport,
        )
        upn = str(me.get("userPrincipalName") or me.get("mail") or "")
        if not upn:
            raise OAuthPrincipalUnresolved(
                provider=self.provider.value, reason="/me returned no userPrincipalName or mail"
            )
        return upn.lower()


__all__ = ["MAIL_READ_SCOPE", "MicrosoftOAuthClient"]

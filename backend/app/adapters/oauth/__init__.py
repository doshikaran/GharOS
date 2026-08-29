"""OAuth Authorization-Code + PKCE clients for the two ingestion providers
(ADR-022). Plain `httpx` — no OAuth library, no provider SDK.

`GoogleOAuthClient` and `MicrosoftOAuthClient` each implement `OAuthClient`
(`base.py`): build the consent URL, exchange an authorization code for a
refresh token (+ first access token + granted scopes + the account
principal), and later exchange that refresh token for a fresh access
token. Nothing here persists anything — the OAuth *routes*
(`app.api.oauth_router`) store the refresh token in Secret Manager and the
`OAuthCredential` reference record in Firestore; the *connectors*
(`app.adapters.connectors`) call `refresh_access_token` at run time and
hold the access token in memory for the length of one `fetch_since`.

**Structural isolation (Gate 14.5):** nothing under `backend/app/agents/`
imports this package. Token material never reaches a reasoning agent.
"""

from __future__ import annotations

from .base import ExchangedTokens, OAuthClient, RefreshedToken
from .errors import OAuthExchangeFailed
from .google import GoogleOAuthClient
from .microsoft import MicrosoftOAuthClient
from .pkce import PkcePair, challenge_for_verifier, generate_pkce_pair

__all__ = [
    "ExchangedTokens",
    "GoogleOAuthClient",
    "MicrosoftOAuthClient",
    "OAuthClient",
    "OAuthExchangeFailed",
    "PkcePair",
    "RefreshedToken",
    "challenge_for_verifier",
    "generate_pkce_pair",
]

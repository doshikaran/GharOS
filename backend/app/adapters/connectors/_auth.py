"""The shared "resolve a stored connection to an in-memory access token"
step both scanning connectors run at the top of `fetch_since` (ADR-022
§2, §4).

Every failure here is one of the four `contracts.errors.IngestionError`
subclasses the orchestrator catches at its per-source boundary — so a
missing connection, a too-narrow grant, or a dead refresh token becomes a
visible `ConnectorFailure`, never a silent empty scan (Gate 14.5,
invariant #7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.errors import (
    OAuthConnectionRequired,
    OAuthScopeInsufficient,
    OAuthTokenRefreshFailed,
)
from contracts.ingestion import OAuthCredential, OAuthCredentialStore, OAuthProvider

from ..oauth.base import OAuthClient
from ..oauth.errors import OAuthExchangeFailed
from ..secret_manager import SecretManagerError


class SecretResolver(Protocol):
    """The one Secret Manager method a connector needs — resolve an
    `OAuthCredential.secret_ref` resource name to the refresh-token
    string. `app.adapters.secret_manager.SecretManagerAdapter` satisfies
    this structurally; it is the ONLY path from a connector to token
    material, and `backend/app/agents/` has no import of it (Gate 14.5)."""

    def get_secret_by_resource_name(self, resource_name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class ResolvedAccess:
    """One run's authenticated context: the in-memory access token (never
    persisted, never logged, never put on an `AgentInput`) and the
    connection record it came from."""

    access_token: str
    credential: OAuthCredential


def resolve_access(
    *,
    provider: OAuthProvider,
    principal: str,
    required_scope: str,
    credential_store: OAuthCredentialStore,
    secret_resolver: SecretResolver,
    oauth_client: OAuthClient,
) -> ResolvedAccess:
    """Load the `(provider, principal)` connection, verify it grants
    `required_scope`, resolve its refresh token from Secret Manager, and
    exchange that for a fresh access token.

    Raises:
        OAuthConnectionRequired: no stored, unrevoked credential.
        OAuthScopeInsufficient: the grant lacks `required_scope`.
        OAuthTokenRefreshFailed: the secret could not be read, or the
            refresh exchange failed (revoked / expired / provider outage).
    """
    credential = credential_store.get(provider, principal)
    if credential is None or not credential.is_active:
        raise OAuthConnectionRequired(provider=provider.value, principal=principal)

    if required_scope not in credential.granted_scopes:
        raise OAuthScopeInsufficient(
            provider=provider.value,
            principal=principal,
            missing_scopes=(required_scope,),
            granted_scopes=credential.granted_scopes,
        )

    try:
        refresh_token = secret_resolver.get_secret_by_resource_name(credential.secret_ref)
    except SecretManagerError as exc:
        raise OAuthTokenRefreshFailed(
            provider=provider.value,
            principal=principal,
            reason=f"could not read the stored refresh token: {exc}",
        ) from exc

    try:
        refreshed = oauth_client.refresh_access_token(refresh_token)
    except OAuthExchangeFailed as exc:
        raise OAuthTokenRefreshFailed(
            provider=provider.value, principal=principal, reason=exc.reason
        ) from exc

    return ResolvedAccess(access_token=refreshed.access_token, credential=credential)


__all__ = ["ResolvedAccess", "SecretResolver", "resolve_access"]

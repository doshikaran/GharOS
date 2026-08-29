"""Shared in-memory test doubles for the Phase 14.5 ingestion-connector
surface (ADR-022 / ADR-023).

Not a test module (no `test_*` name — never collected). Mirrors
`_gemini_fakes.py` / `_fake_raw_payload_store.py`: real objects that
satisfy the frozen `contracts.ingestion` Protocols (and the E3-side
OAuth-client / Secret-Manager shapes) with zero network access, so the
connector, orchestrator, and router tests never touch Google, Microsoft,
Firestore-for-credentials, or Secret Manager.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from contracts.ingestion import (
    IngestionSourceKind,
    OAuthCredential,
    OAuthProvider,
    RawIntakePayload,
)

from app.adapters.oauth.base import ExchangedTokens, RefreshedToken
from app.adapters.oauth.errors import OAuthExchangeFailed
from app.persistence.oauth_pending_store import OAuthPendingRecord


def make_oauth_credential(
    *,
    provider: OAuthProvider = OAuthProvider.GOOGLE,
    principal: str = "alice@example.com",
    granted_scopes: tuple[str, ...] = ("openid", "email"),
    secret_ref: str = "projects/p/secrets/gharos-oauth-refresh--google--alice-example-com/versions/1",
    connected_at: datetime | None = None,
    last_scan_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> OAuthCredential:
    return OAuthCredential(
        provider=provider,
        principal=principal,
        granted_scopes=granted_scopes,
        secret_ref=secret_ref,
        connected_at=connected_at or datetime(2026, 8, 25, tzinfo=UTC),
        last_scan_at=last_scan_at,
        revoked_at=revoked_at,
    )


class FakeSourceConnector:
    """Structurally satisfies `contracts.ingestion.SourceConnector` — hands
    the orchestrator a fixed list of `RawIntakePayload`s (or raises a
    supplied exception, to exercise the per-source `ConnectorFailure`
    boundary)."""

    def __init__(
        self,
        kind: IngestionSourceKind,
        payloads: Sequence[RawIntakePayload],
        *,
        raises: Exception | None = None,
    ) -> None:
        self.kind = kind
        self._payloads = list(payloads)
        self._raises = raises
        self.calls: list[tuple[float, str]] = []

    def fetch_since(self, window: object, *, principal: str) -> Sequence[RawIntakePayload]:
        self.calls.append((getattr(window, "total_seconds", lambda: 0.0)(), principal))
        if self._raises is not None:
            raise self._raises
        return list(self._payloads)


class FakeOAuthCredentialStore:
    """In-memory `contracts.ingestion.OAuthCredentialStore`."""

    def __init__(self, credentials: Sequence[OAuthCredential] = ()) -> None:
        self._by_key: dict[tuple[OAuthProvider, str], OAuthCredential] = {
            (c.provider, c.principal): c for c in credentials
        }
        self.revoked: list[tuple[OAuthProvider, str, datetime]] = []
        self.touched: list[tuple[OAuthProvider, str, datetime]] = []

    def get(self, provider: OAuthProvider, principal: str) -> OAuthCredential | None:
        return self._by_key.get((provider, principal))

    def list_active(self) -> tuple[OAuthCredential, ...]:
        return tuple(c for c in self._by_key.values() if c.revoked_at is None)

    def put(self, credential: OAuthCredential) -> None:
        self._by_key[(credential.provider, credential.principal)] = credential

    def mark_revoked(self, provider: OAuthProvider, principal: str, *, revoked_at: datetime) -> None:
        self.revoked.append((provider, principal, revoked_at))
        existing = self._by_key.get((provider, principal))
        if existing is not None and existing.revoked_at is None:
            self._by_key[(provider, principal)] = make_oauth_credential(
                provider=existing.provider,
                principal=existing.principal,
                granted_scopes=existing.granted_scopes,
                secret_ref=existing.secret_ref,
                connected_at=existing.connected_at,
                last_scan_at=existing.last_scan_at,
                revoked_at=revoked_at,
            )

    def touch_last_scan(self, provider: OAuthProvider, principal: str, *, at: datetime) -> None:
        self.touched.append((provider, principal, at))


class FakeSecretResolver:
    """The one method a connector needs off Secret Manager, plus the read
    method the routes use — returns a fixed refresh-token string."""

    def __init__(self, refresh_token: str = "refresh-token-value") -> None:
        self._refresh_token = refresh_token
        self.resolved: list[str] = []

    def get_secret_by_resource_name(self, resource_name: str) -> str:
        self.resolved.append(resource_name)
        return self._refresh_token

    def get_secret(self, secret_id: str, *, version: str = "latest") -> str:
        return "client-secret-value"


class FakeSecretWriteAdapter:
    """In-memory stand-in for `SecretManagerWriteAdapter`."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.destroyed: list[str] = []

    def put_secret(self, secret_id: str, payload: str) -> str:
        self.put_calls.append((secret_id, payload))
        return f"projects/test/secrets/{secret_id}/versions/1"

    def destroy_all_versions(self, secret_id: str) -> int:
        self.destroyed.append(secret_id)
        return 1


class StubOAuthClient:
    """Structurally satisfies `app.adapters.oauth.base.OAuthClient`."""

    def __init__(
        self,
        *,
        provider: OAuthProvider = OAuthProvider.GOOGLE,
        principal: str = "alice@example.com",
        granted_scopes: tuple[str, ...] = ("openid", "email"),
        refresh_fails: bool = False,
    ) -> None:
        self.provider = provider
        self._principal = principal
        self._granted_scopes = granted_scopes
        self._refresh_fails = refresh_fails
        self.exchanged: list[tuple[str, str]] = []

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        return (
            f"https://provider.example/auth?state={state}"
            f"&code_challenge={code_challenge}&code_challenge_method=S256"
        )

    def exchange_code(self, *, code: str, code_verifier: str) -> ExchangedTokens:
        self.exchanged.append((code, code_verifier))
        return ExchangedTokens(
            refresh_token="refresh-token-from-exchange",
            access_token="access-token-from-exchange",
            expires_in=3600,
            granted_scopes=self._granted_scopes,
            principal=self._principal,
        )

    def refresh_access_token(self, refresh_token: str) -> RefreshedToken:
        if self._refresh_fails:
            raise OAuthExchangeFailed(
                provider=self.provider.value,
                stage="token-refresh",
                reason="invalid_grant",
                invalid_grant=True,
            )
        return RefreshedToken(access_token="fresh-access-token", expires_in=3600)


class InMemoryOAuthPendingStore:
    """In-memory `app.persistence.oauth_pending_store.OAuthPendingStore` —
    single-use, no TTL modelling (tests that need TTL use the real
    Firestore store with an injected clock)."""

    def __init__(self) -> None:
        self._by_state: dict[str, OAuthPendingRecord] = {}

    def put_pending(self, state: str, *, code_verifier: str, principal_hint: str | None) -> None:
        self._by_state[state] = OAuthPendingRecord(
            code_verifier=code_verifier,
            principal_hint=principal_hint,
            created_at=datetime.now(UTC),
        )

    def take_pending(self, state: str) -> OAuthPendingRecord | None:
        return self._by_state.pop(state, None)


__all__ = [
    "FakeOAuthCredentialStore",
    "FakeSecretResolver",
    "FakeSecretWriteAdapter",
    "FakeSourceConnector",
    "InMemoryOAuthPendingStore",
    "StubOAuthClient",
    "make_oauth_credential",
]

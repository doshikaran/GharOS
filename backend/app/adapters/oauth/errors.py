"""OAuth-client-layer failures (ADR-022). Distinct from
`contracts.errors.IngestionError`: those are the *connector* preconditions
the orchestrator converts into `ConnectorFailure` run data. `OAuthExchange
Failed` is raised by the token-endpoint round trips themselves — the OAuth
*callback route* maps it to an HTTP response + a failure marker on the
redirect back to the Connections page, and a *connector* wraps it into the
appropriate `contracts.errors` subclass with its `(provider, principal)`
context before the orchestrator ever sees it.

Invariant #7 (no fabricated success) reaches this surface: a failed code
exchange or token refresh raises here — it never returns an empty or
placeholder token.
"""

from __future__ import annotations


class OAuthExchangeFailed(RuntimeError):
    """A call to a provider token endpoint (authorization-code exchange or
    refresh-token exchange) failed.

    `invalid_grant` is `True` when the provider returned the OAuth
    `invalid_grant` error (or a Microsoft `AADSTS700082`/`AADSTS50173`
    equivalent) — the refresh token is revoked or expired (including an
    expired 7-day OAuth-test-mode Google token, ADR-022 §4) and the user
    must reconnect. `False` for a transport error, a 5xx, or an
    unparseable response.
    """

    def __init__(self, *, provider: str, stage: str, reason: str, invalid_grant: bool) -> None:
        self.provider = provider
        self.stage = stage
        self.reason = reason
        self.invalid_grant = invalid_grant
        super().__init__(f"{provider} OAuth {stage} failed: {reason} (invalid_grant={invalid_grant})")


class OAuthPrincipalUnresolved(OAuthExchangeFailed):
    """The code exchange succeeded but the account identity (Google
    `email` from the verified `id_token`, Microsoft `userPrincipalName`
    from `/me`) could not be established — the callback must not write an
    `OAuthCredential` with an unknown principal."""

    def __init__(self, *, provider: str, reason: str) -> None:
        super().__init__(provider=provider, stage="principal-resolution", reason=reason, invalid_grant=False)


__all__ = ["OAuthExchangeFailed", "OAuthPrincipalUnresolved"]

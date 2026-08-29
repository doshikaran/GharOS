"""Shared HTTP plumbing for the Gmail / Outlook / Drive connectors:
one `httpx` GET with bounded exponential backoff on `429` and `5xx`, and a
single place that turns every failure mode into the right
`contracts.errors` subclass so the orchestrator's per-source boundary can
classify it (`is_auth_failure` vs transient).

Never returns a partial / fabricated result: a call that never succeeds
raises `ConnectorFetchFailed`; a `401`/`403` raises `OAuthTokenRefresh
Failed` so the Connections UI shows a reconnect prompt (Gate 14.5).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

import httpx
import structlog
from contracts.errors import ConnectorFetchFailed, OAuthTokenRefreshFailed

logger = structlog.get_logger(__name__)

DEFAULT_MAX_ATTEMPTS = 4
_BASE_BACKOFF_SECONDS = 0.5
_REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


_MAX_RETRY_AFTER_SECONDS = 30.0


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    header: str = response.headers.get("Retry-After", "").strip()
    if header.isdigit():
        seconds = float(int(header))
        return seconds if seconds < _MAX_RETRY_AFTER_SECONDS else _MAX_RETRY_AFTER_SECONDS
    return _BASE_BACKOFF_SECONDS * float(2**attempt)


def get_with_backoff(
    url: str,
    *,
    access_token: str,
    provider: str,
    principal: str,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Authenticated GET with retry/backoff. Returns the successful
    `httpx.Response`.

    Raises:
        OAuthTokenRefreshFailed: the API answered `401`/`403` — the grant
            is not usable; surface a reconnect prompt.
        ConnectorFetchFailed: a transport error, or `429`/`5xx` that
            survived `max_attempts` retries, or any other non-2xx.
    """
    merged_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)

    # Pass `params` only when there is something to send: httpx STRIPS an
    # existing query string from `url` when a (even empty) `params` kwarg
    # is given, which would silently break `@odata.nextLink` / any
    # already-parameterised follow-up URL the connectors page through.
    request_params: dict[str, str] | None = dict(params) if params else None

    last_reason = "no attempt made"
    with httpx.Client(transport=transport, timeout=_REQUEST_TIMEOUT) as client:
        for attempt in range(max_attempts):
            try:
                response = client.get(url, params=request_params, headers=merged_headers)
            except httpx.HTTPError as exc:
                last_reason = f"transport error: {exc}"
                logger.warning(
                    "connectors.http.transport_error", provider=provider, attempt=attempt, error=str(exc)
                )
                if attempt + 1 < max_attempts:
                    sleep(_BASE_BACKOFF_SECONDS * (2**attempt))
                    continue
                break

            if response.is_success:
                return response

            if response.status_code in (401, 403):
                raise OAuthTokenRefreshFailed(
                    provider=provider,
                    principal=principal,
                    reason=f"provider returned HTTP {response.status_code} for an authenticated request",
                )

            if response.status_code == 429 or response.status_code >= 500:
                last_reason = f"HTTP {response.status_code}"
                logger.warning(
                    "connectors.http.retryable_status",
                    provider=provider,
                    attempt=attempt,
                    status=response.status_code,
                )
                if attempt + 1 < max_attempts:
                    sleep(_retry_after_seconds(response, attempt))
                    continue
                raise ConnectorFetchFailed(
                    provider=provider,
                    principal=principal,
                    reason=f"{last_reason} after {max_attempts} attempts",
                    retryable=True,
                )

            raise ConnectorFetchFailed(
                provider=provider,
                principal=principal,
                reason=f"HTTP {response.status_code}: {response.text[:200]}",
                retryable=False,
            )

    raise ConnectorFetchFailed(
        provider=provider,
        principal=principal,
        reason=f"{last_reason} after {max_attempts} attempts",
        retryable=True,
    )


__all__ = ["DEFAULT_MAX_ATTEMPTS", "get_with_backoff"]

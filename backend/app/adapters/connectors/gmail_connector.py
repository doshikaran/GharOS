"""`GmailConnector` — `contracts.ingestion.SourceConnector` for Gmail
(Phase 14.5, ADR-023).

Real Gmail REST API, `httpx`, no `google-api-python-client`:

- `users.messages.list?q=after:<epoch>` (paginated on `nextPageToken`) to
  enumerate the message ids received inside the window,
- `users.messages.get?format=full` per id,
- MIME tree -> the `{headers: {"from","subject","to","date",...}, text:
  <plain-text body>}` shape `email_adapter.normalize` consumes, with
  `headers[EXTERNAL_IDENTITY_HEADER]` set to the Gmail message id.

Token acquisition, scope enforcement, and quota/backoff are shared
(`_auth.resolve_access`, `_http.get_with_backoff`). Every failure is a
typed `contracts.errors.IngestionError` — never a silent partial result.
"""

from __future__ import annotations

import base64
import binascii
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from contracts.errors import ConnectorFetchFailed
from contracts.ingestion import (
    EXTERNAL_IDENTITY_HEADER,
    IngestionSourceKind,
    OAuthCredentialStore,
    OAuthProvider,
    RawIntakePayload,
)

from ..oauth.base import OAuthClient
from ..oauth.google import GMAIL_READONLY_SCOPE
from ._auth import SecretResolver, resolve_access
from ._http import get_with_backoff
from ._mime import html_to_text

logger = structlog.get_logger(__name__)

_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
_LIST_PAGE_SIZE = "100"
_MAX_MESSAGES_PER_SCAN = 250
"""A hard ceiling on one 24h scan so a mislabelled window or a bulk import
cannot fan out into hundreds of Flash extraction calls (PHASES.md §6 cost
discipline). Reaching it is logged, not silently truncated."""

_PROVIDER = OAuthProvider.GOOGLE
_WANTED_HEADERS = {"from", "to", "cc", "subject", "date", "reply-to", "message-id"}


class GmailConnector:
    """`SourceConnector` for `IngestionSourceKind.GMAIL`."""

    kind = IngestionSourceKind.GMAIL

    def __init__(
        self,
        *,
        credential_store: OAuthCredentialStore,
        secret_resolver: SecretResolver,
        oauth_client: OAuthClient,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credential_store = credential_store
        self._secret_resolver = secret_resolver
        self._oauth_client = oauth_client
        self._transport = transport
        self._sleep = sleep

    def fetch_since(self, window: timedelta, *, principal: str) -> Sequence[RawIntakePayload]:
        access = resolve_access(
            provider=_PROVIDER,
            principal=principal,
            required_scope=GMAIL_READONLY_SCOPE,
            credential_store=self._credential_store,
            secret_resolver=self._secret_resolver,
            oauth_client=self._oauth_client,
        )
        after_epoch = int((datetime.now(UTC) - window).timestamp())
        message_ids = self._list_message_ids(access.access_token, principal, after_epoch)
        logger.info(
            "connectors.gmail.listed",
            principal=principal,
            message_count=len(message_ids),
            after=after_epoch,
        )
        return [self._fetch_one(access.access_token, principal, mid) for mid in message_ids]

    # -- listing --------------------------------------------------------

    def _list_message_ids(self, access_token: str, principal: str, after_epoch: int) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while True:
            params = {"q": f"after:{after_epoch}", "maxResults": _LIST_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            body = self._get_json(f"{_API_ROOT}/messages", access_token, principal, params, "messages.list")
            raw_messages = body.get("messages")
            for entry in raw_messages if isinstance(raw_messages, list) else []:
                if isinstance(entry, dict) and entry.get("id"):
                    ids.append(str(entry["id"]))
                    if len(ids) >= _MAX_MESSAGES_PER_SCAN:
                        logger.warning(
                            "connectors.gmail.scan_ceiling_reached",
                            principal=principal,
                            ceiling=_MAX_MESSAGES_PER_SCAN,
                        )
                        return ids
            next_token = body.get("nextPageToken")
            if not next_token:
                return ids
            page_token = str(next_token)

    # -- per-message --------------------------------------------------

    def _fetch_one(self, access_token: str, principal: str, message_id: str) -> RawIntakePayload:
        message = self._get_json(
            f"{_API_ROOT}/messages/{message_id}",
            access_token,
            principal,
            {"format": "full"},
            f"messages.get[{message_id}]",
        )
        payload_node = message.get("payload")
        payload_node = payload_node if isinstance(payload_node, dict) else {}
        headers = _collect_headers(payload_node)
        headers[EXTERNAL_IDENTITY_HEADER] = message_id
        body_text = _extract_plain_text(payload_node) or str(message.get("snippet") or "")
        return RawIntakePayload(
            text=body_text or None,
            binary=None,
            media_type="text/plain",
            headers=headers,
            received_at=_received_at(message),
        )

    # -- http ------------------------------------------------------

    def _get_json(
        self,
        url: str,
        access_token: str,
        principal: str,
        params: dict[str, str],
        stage: str,
    ) -> dict[str, object]:
        response = get_with_backoff(
            url,
            access_token=access_token,
            provider=_PROVIDER.value,
            principal=principal,
            params=params,
            transport=self._transport,
            sleep=self._sleep,
        )
        try:
            parsed = response.json()
        except ValueError as exc:
            raise ConnectorFetchFailed(
                provider=_PROVIDER.value,
                principal=principal,
                reason=f"{stage}: response was not JSON ({exc})",
                retryable=False,
            ) from exc
        if not isinstance(parsed, dict):
            raise ConnectorFetchFailed(
                provider=_PROVIDER.value,
                principal=principal,
                reason=f"{stage}: expected a JSON object",
                retryable=False,
            )
        return parsed


# ---------------------------------------------------------------------------
# MIME helpers (module-level, pure)
# ---------------------------------------------------------------------------


def _collect_headers(payload_node: dict[str, object]) -> dict[str, str]:
    collected: dict[str, str] = {}
    raw_headers = payload_node.get("headers")
    if not isinstance(raw_headers, list):
        return collected
    for header in raw_headers:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name", "")).lower()
        value = str(header.get("value", ""))
        if name in _WANTED_HEADERS and value:
            collected[name] = value
    return collected


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        return b""


def _extract_plain_text(payload_node: dict[str, object]) -> str:
    """Depth-first walk of the MIME tree: prefer the first `text/plain`
    part; fall back to the first `text/html` part rendered to text."""
    plain = _first_part_of_type(payload_node, "text/plain")
    if plain:
        return plain
    html = _first_part_of_type(payload_node, "text/html")
    return html_to_text(html) if html else ""


def _first_part_of_type(node: dict[str, object], mime_type: str) -> str:
    node_mime = str(node.get("mimeType", "")).lower()
    body = node.get("body")
    if node_mime == mime_type and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, str) and data:
            decoded = _b64url_decode(data)
            if decoded:
                return decoded.decode("utf-8", errors="replace")
    parts = node.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                found = _first_part_of_type(part, mime_type)
                if found:
                    return found
    return ""


def _received_at(message: dict[str, object]) -> datetime:
    internal_date = message.get("internalDate")
    if isinstance(internal_date, (str, int)):
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
        except (ValueError, OverflowError, OSError):
            pass
    return datetime.now(UTC)


__all__ = ["GmailConnector"]

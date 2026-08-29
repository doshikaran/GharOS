"""`OutlookConnector` — `contracts.ingestion.SourceConnector` for Outlook
via Microsoft Graph (Phase 14.5, ADR-023).

`GET /me/messages?$filter=receivedDateTime ge <iso>&$select=id,from,
toRecipients,subject,receivedDateTime,body,bodyPreview&$top=...`, paged on
`@odata.nextLink`. Each Graph message becomes the same `{headers, text}`
`RawIntakePayload` shape `email_adapter.normalize` consumes, with
`headers[EXTERNAL_IDENTITY_HEADER]` set to the Graph message id.

Shares token acquisition / scope enforcement / backoff with the Gmail
connector; every failure is a typed `contracts.errors.IngestionError`.
"""

from __future__ import annotations

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
from ..oauth.microsoft import MAIL_READ_SCOPE
from ._auth import SecretResolver, resolve_access
from ._http import get_with_backoff
from ._mime import html_to_text

logger = structlog.get_logger(__name__)

_MESSAGES_ENDPOINT = "https://graph.microsoft.com/v1.0/me/messages"
_SELECT = "id,from,toRecipients,ccRecipients,subject,receivedDateTime,body,bodyPreview"
_PAGE_SIZE = "50"
_MAX_MESSAGES_PER_SCAN = 250
_PROVIDER = OAuthProvider.MICROSOFT


class OutlookConnector:
    """`SourceConnector` for `IngestionSourceKind.OUTLOOK`."""

    kind = IngestionSourceKind.OUTLOOK

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
            required_scope=MAIL_READ_SCOPE,
            credential_store=self._credential_store,
            secret_resolver=self._secret_resolver,
            oauth_client=self._oauth_client,
        )
        since_iso = (datetime.now(UTC) - window).strftime("%Y-%m-%dT%H:%M:%SZ")
        messages = self._list_messages(access.access_token, principal, since_iso)
        logger.info(
            "connectors.outlook.listed", principal=principal, message_count=len(messages), since=since_iso
        )
        return [_to_payload(message) for message in messages]

    def _list_messages(self, access_token: str, principal: str, since_iso: str) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        url: str | None = _MESSAGES_ENDPOINT
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_iso}",
            "$select": _SELECT,
            "$orderby": "receivedDateTime desc",
            "$top": _PAGE_SIZE,
        }
        while url is not None:
            body = self._get_json(url, access_token, principal, params)
            raw_value = body.get("value")
            for entry in raw_value if isinstance(raw_value, list) else []:
                if isinstance(entry, dict) and entry.get("id"):
                    messages.append(entry)
                    if len(messages) >= _MAX_MESSAGES_PER_SCAN:
                        logger.warning(
                            "connectors.outlook.scan_ceiling_reached",
                            principal=principal,
                            ceiling=_MAX_MESSAGES_PER_SCAN,
                        )
                        return messages
            next_link = body.get("@odata.nextLink")
            url = str(next_link) if next_link else None
            params = None  # nextLink already carries the query string
        return messages

    def _get_json(
        self,
        url: str,
        access_token: str,
        principal: str,
        params: dict[str, str] | None,
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
                reason=f"messages: response was not JSON ({exc})",
                retryable=False,
            ) from exc
        if not isinstance(parsed, dict):
            raise ConnectorFetchFailed(
                provider=_PROVIDER.value,
                principal=principal,
                reason="messages: expected a JSON object",
                retryable=False,
            )
        return parsed


# ---------------------------------------------------------------------------
# Graph JSON -> RawIntakePayload (pure)
# ---------------------------------------------------------------------------


def _address(entry: object) -> str:
    if isinstance(entry, dict):
        email_address = entry.get("emailAddress")
        if isinstance(email_address, dict):
            return str(email_address.get("address") or email_address.get("name") or "")
    return ""


def _recipient_list(entries: object) -> str:
    if not isinstance(entries, list):
        return ""
    return ", ".join(addr for addr in (_address(e) for e in entries) if addr)


def _body_text(message: dict[str, object]) -> str:
    body = message.get("body")
    if isinstance(body, dict):
        content = str(body.get("content") or "")
        if str(body.get("contentType") or "").lower() == "html":
            rendered = html_to_text(content)
            if rendered:
                return rendered
        elif content.strip():
            return content
    return str(message.get("bodyPreview") or "")


def _received_at(message: dict[str, object]) -> datetime:
    raw = message.get("receivedDateTime")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _to_payload(message: dict[str, object]) -> RawIntakePayload:
    headers: dict[str, str] = {EXTERNAL_IDENTITY_HEADER: str(message["id"])}
    sender = _address(message.get("from"))
    if sender:
        headers["from"] = sender
    subject = str(message.get("subject") or "")
    if subject:
        headers["subject"] = subject
    to_line = _recipient_list(message.get("toRecipients"))
    if to_line:
        headers["to"] = to_line
    cc_line = _recipient_list(message.get("ccRecipients"))
    if cc_line:
        headers["cc"] = cc_line
    received = _received_at(message)
    headers["date"] = received.strftime("%a, %d %b %Y %H:%M:%S %z")
    body_text = _body_text(message)
    return RawIntakePayload(
        text=body_text or None,
        binary=None,
        media_type="text/plain",
        headers=headers,
        received_at=received,
    )


__all__ = ["OutlookConnector"]

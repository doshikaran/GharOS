"""GharOS — Pub/Sub push receiver (PHASES.md Phase 2 work items 2 and 5).

Cloud Scheduler publishes a `contracts.events.ScheduledTickPayload` onto
the `gharos-heartbeat` Pub/Sub topic (`infra/scheduler_jobs.sh`); a push
subscription on that topic (`infra/pubsub_topics.sh`) delivers it here as
an HTTP POST, in Pub/Sub's real push envelope shape
(https://cloud.google.com/pubsub/docs/push#receive_push):

    {
      "message": {
        "data": "<base64>",
        "attributes": {...},
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "projects/.../subscriptions/..."
    }

This module parses that real shape (never a flattened/simplified stand-in
for it) and, when `Settings.pubsub_push_service_account_email` is
configured, cryptographically verifies the request actually came from
Pub/Sub via the OIDC identity token Pub/Sub attaches when the push
subscription is created with `--push-auth-service-account`
(`infra/pubsub_topics.sh`). This is the only inbound HTTP surface in the
GharOS backend that Pub/Sub itself calls — everything else is invoked by a
human, a reasoning agent through the graph, or the Approval Gate.

This is Layer 0 (ingestion) in spec §6.2's layering, not Layer 5 (action):
receiving a heartbeat tick is not a T-tiered tool call and does not itself
touch the outside world, so it carries no permission tier and needs no
Approval Gate — it is the entry point that will, in later phases, publish
a `ScheduledTickPayload`-shaped event onward into the routing layer
(`contracts.events.SubsystemName`) for the Consolidation, Ledger, and
Concierge follow-up cycles (PHASES.md §7, §10, §14) to consume.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel, ConfigDict, Field

from app.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/events", tags=["pubsub"])


class PubSubMessage(BaseModel):
    """The `message` object inside a real Pub/Sub push envelope."""

    model_config = ConfigDict(populate_by_name=True)

    data: str | None = None
    """Base64-encoded message body. Optional — an attributes-only message
    (no payload) is valid Pub/Sub."""
    message_id: str = Field(alias="messageId")
    publish_time: str = Field(alias="publishTime")
    attributes: dict[str, str] = Field(default_factory=dict)


class PubSubPushEnvelope(BaseModel):
    """The full HTTP POST body Pub/Sub sends to a push endpoint."""

    message: PubSubMessage
    subscription: str


TokenVerifier = Callable[[str, str], dict[str, Any]]
"""`(token, audience) -> decoded claims`. Injected so tests can substitute
a fake verifier instead of making a real network call to fetch Google's
public certificates — production wiring uses `_verify_google_oidc_token`
(gharos-standards: dependency injection, no hidden I/O)."""


def _verify_google_oidc_token(token: str, audience: str) -> dict[str, Any]:
    """Cryptographically verifies a Google-issued OIDC identity token
    against Google's public certificates and the expected audience.
    Raises on any invalid, expired, or wrong-audience token — never
    returns claims for a token that didn't verify."""
    request = google_auth_requests.Request()
    # `verify_oauth2_token` ships no parameter/return annotations in
    # google-auth's own source (confirmed via `inspect.signature` against the
    # installed package — it is marked py.typed but this particular function
    # predates the library's annotation coverage), so `mypy --strict` flags
    # the call itself as untyped even though the module is otherwise typed.
    # The cryptographic verification this line performs is real; only the
    # stub coverage is missing, so a narrow, commented ignore on this one
    # call is correct here rather than a broader suppression.
    claims: dict[str, Any] = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        token, request, audience=audience
    )
    return claims


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def verify_push_request(
    *,
    authorization: str | None,
    settings: Settings,
    verifier: TokenVerifier = _verify_google_oidc_token,
) -> None:
    """Verifies an inbound push request is genuinely from Pub/Sub.

    Verification is skipped, with a logged warning, only when
    `settings.pubsub_push_service_account_email` is unset — the
    local/emulator development path, where no push subscription (and
    therefore no OIDC token) exists at all. A real deployment always sets
    this once `infra/pubsub_topics.sh` has wired the push subscription
    against the live service URL, so production traffic is never silently
    left unverified.

    Raises:
        HTTPException: 401 if verification is required and the request
            lacks a valid bearer token, the token fails cryptographic
            verification, or the token identity does not match the
            configured service account.
    """
    expected_service_account = settings.pubsub_push_service_account_email
    if not expected_service_account:
        logger.warning(
            "pubsub_push_verification_skipped",
            reason="no pubsub_push_service_account_email configured (local/emulator dev path)",
        )
        return

    token = _extract_bearer_token(authorization)
    if token is None:
        logger.warning("pubsub_push_rejected", reason="missing or malformed bearer token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    audience = settings.pubsub_push_audience or expected_service_account
    try:
        claims = verifier(token, audience)
    except (GoogleAuthError, ValueError) as exc:
        logger.warning("pubsub_push_rejected", reason="token failed verification", error=str(exc))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc

    token_identity = claims.get("email")
    if token_identity != expected_service_account:
        logger.warning(
            "pubsub_push_rejected",
            reason="token identity mismatch",
            got=token_identity,
            expected=expected_service_account,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unexpected token identity")


def _decode_message_data(message: PubSubMessage) -> dict[str, Any] | str | None:
    """Decodes `message.data` from base64 and, where the decoded bytes are
    valid JSON, parses it. Returns `None` for an attributes-only message,
    or the raw decoded text when the payload isn't JSON (Cloud Scheduler's
    Pub/Sub target always sends a JSON body — `infra/scheduler_jobs.sh` —
    but this receiver does not assume that of every future publisher on
    this topic).

    Raises:
        HTTPException: 400 if `message.data` is present but not valid
            base64 — a malformed envelope, not a valid heartbeat.
    """
    if message.data is None:
        return None
    try:
        raw = base64.b64decode(message.data, validate=True)
    except binascii.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="message.data is not valid base64"
        ) from exc
    try:
        decoded: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode("utf-8", errors="replace")
    return decoded


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def receive_heartbeat(
    envelope: PubSubPushEnvelope,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Receives the Cloud Scheduler heartbeat tick pushed by Pub/Sub.

    Target of the `gharos-heartbeat` topic's push subscription
    (`infra/pubsub_topics.sh`), fed by the `gharos-heartbeat-tick` Cloud
    Scheduler job (`infra/scheduler_jobs.sh`). This closes the Gate 2
    round trip: Cloud Scheduler -> Pub/Sub -> Cloud Run, unattended.

    Always returns 204 on a successfully verified and parsed push (Pub/Sub
    treats any non-2xx as delivery failure and retries per the
    subscription's retry policy) — a malformed envelope (400) or failed
    verification (401) are the only rejection paths, and both are real
    rejections, never a fabricated 204 (gharos-standards non-negotiable
    #7).
    """
    verify_push_request(authorization=authorization, settings=settings)
    payload = _decode_message_data(envelope.message)
    logger.info(
        "heartbeat_received",
        message_id=envelope.message.message_id,
        publish_time=envelope.message.publish_time,
        subscription=envelope.subscription,
        attributes=envelope.message.attributes,
        payload=payload,
    )

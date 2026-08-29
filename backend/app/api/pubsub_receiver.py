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

Phase 14 (ADR-021 Decision 3) adds `POST /events/consolidation-nightly`:
the `gharos-consolidation-nightly` Cloud Scheduler job
(`infra/scheduler_jobs.sh`) publishing onto its own dedicated
`gharos-consolidation-nightly` Pub/Sub topic (`infra/pubsub_topics.sh`),
delivered here in the identical envelope shape and push-verification path
as the heartbeat and follow-up-sweep routes above it. Unlike those two
(which are deliberately thin — proving the mechanism, not yet consuming
it), this route actually invokes the Memory Consolidation service
(`app.graph.consolidation_service`, E1, ADR-021 Decisions 1-3) — see
`invoke_nightly_consolidation`'s docstring for the exact entry-point shape
assumed and why the import is deferred to call time rather than module
load time.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from datetime import UTC, datetime
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


@router.post("/followup-sweep", status_code=status.HTTP_204_NO_CONTENT)
async def receive_followup_sweep(
    envelope: PubSubPushEnvelope,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Receives the A31 Follow-up/Persistence Cloud Scheduler tick
    (PHASES.md Phase 7) — the `gharos-followup-sweep` job
    (`infra/scheduler_jobs.sh`) publishing a `contracts.events.
    ScheduledTickPayload` onto the `gharos-followup-sweep` topic
    (`infra/pubsub_topics.sh`), delivered here exactly as `receive_heartbeat`
    is, above (same envelope shape, same push-auth verification).

    **Deliberately thin, matching `receive_heartbeat`'s own documented
    intent** ("the entry point that will, in later phases, publish... for
    the... Ledger... follow-up cycles... to consume"): this route verifies
    the push and logs the tick's receipt — real, auditable evidence a
    genuine unattended sweep occurred (`docs/DEPLOYMENT_PROOF.md`'s
    Cloud-Logging-export requirement). It does not itself construct
    `app.events.followup_scan.FollowUpScanner` / `app.events.
    followup_dispatcher.FollowUpDispatcher` here, because doing so
    honestly needs: (a) a live provider of open, trackable items — which
    needs A30's `RecoveryDraft` (E2, parallel Phase-7 work, not
    guaranteed to exist yet) to be a real, graph-queryable type, and a
    `GraphReader`/repository method to enumerate it, which does not exist
    on the frozen contract today (see `followup_scan.py`'s module
    docstring); and (b) a composition-root DI wiring for `EventPublisher`/
    `EscalationAgent`/`GraphReader` this codebase has not yet established
    anywhere. Wiring both is real work for whichever phase lands A30 and
    the composition root together — not something to fake here with an
    empty-list provider dressed up as a live integration. `FollowUpScanner`
    and `FollowUpDispatcher` are themselves complete, real, and fully unit-
    tested (`backend/tests/test_followup_scan.py`,
    `test_followup_dispatcher.py`) — only this route's wiring to them is
    the deferred piece, and it is deferred openly, not silently.
    """
    verify_push_request(authorization=authorization, settings=settings)
    payload = _decode_message_data(envelope.message)
    logger.info(
        "followup_sweep_tick_received",
        message_id=envelope.message.message_id,
        publish_time=envelope.message.publish_time,
        subscription=envelope.subscription,
        attributes=envelope.message.attributes,
        payload=payload,
    )


_CONSOLIDATION_NIGHTLY_JOB_NAME = "gharos-consolidation-nightly"

ConsolidationRunner = Callable[[str], object]
"""`(cycle_label) -> ConsolidationRunSummary`. Injected exactly like
`TokenVerifier` above and for the same reason: testability without a real
call to the thing being wrapped. Return type is `object`, not
`ConsolidationRunSummary`, because this module (`backend/app/api/`, E3)
must import cleanly whether or not `app.graph.consolidation_service`
(E1, landing in parallel this phase per ADR-021 Decision 3) exists yet —
see `_default_consolidation_runner`."""


def _default_consolidation_runner(cycle_label: str) -> object:
    """Lazily imports and invokes E1's Memory Consolidation service entry
    point. The import is deferred to call time — not module load time —
    so this receiver module (and therefore `app.main`, and therefore
    every test that imports it) does not hard-fail merely because
    `app.graph.consolidation_service` has not landed yet; only an actual
    nightly-consolidation invocation needs it to be present.

    Assumed shape (documented here for E1 to reconcile against once their
    real module lands, same seam as Phase 13's E3/E2 dispatch, which
    needed one small follow-up afterward — expected, not a defect):

        # backend/app/graph/consolidation_service.py
        def run_nightly_consolidation(*, cycle_label: str) -> ConsolidationRunSummary: ...

    `ConsolidationRunSummary` is whatever dataclass/model E1 defines to
    carry the run's pattern counts / maintenance actions (ADR-021
    Decisions 1-2); this function returns it untouched. Only its
    presence and `str()`-ability are relied on by the caller for logging.

    Raises whatever `run_nightly_consolidation` raises, including
    `ImportError` if the module is not present yet — never swallowed into
    a fabricated success (gharos-standards non-negotiable #7).
    """
    from app.graph.consolidation_service import run_nightly_consolidation

    result: object = run_nightly_consolidation(cycle_label=cycle_label)
    return result


def invoke_nightly_consolidation(cycle_label: str, *, runner: ConsolidationRunner | None = None) -> object:
    """Invokes the Memory Consolidation service entry point for one
    nightly cycle.

    `runner` defaults to `None`, in which case the module-level
    `_default_consolidation_runner` is looked up **by name at call
    time** (not bound as a parameter default) — this is deliberate: a
    parameter default is evaluated once, at function-definition time, so
    binding it directly would freeze in whichever function object existed
    when this module was first imported, defeating a test's ability to
    monkeypatch `app.api.pubsub_receiver._default_consolidation_runner`
    and have the route pick up the replacement.

    Raises whatever the runner raises — a failed consolidation run must
    reach the caller as a real failure (surfaced as a 500 to Pub/Sub,
    which retries per the subscription's retry policy), never swallowed
    into a fabricated 204 (gharos-standards non-negotiable #7, mirrored
    from `receive_heartbeat`'s own documented posture on malformed input).
    """
    active_runner = runner if runner is not None else _default_consolidation_runner
    return active_runner(cycle_label)


def _derive_consolidation_cycle_label(publish_time: str) -> str:
    """Derives the per-run `cycle_label` (`YYYY-MM-DD`) for a nightly
    consolidation tick from Pub/Sub's own `publishTime` on the envelope.

    Same reasoning `receive_heartbeat`'s module-level docstring already
    documents for `ScheduledTickPayload.scheduled_for`: Cloud Scheduler's
    Pub/Sub-target message body is a static string baked in at job
    create/update time (`infra/scheduler_jobs.sh`), so it cannot carry a
    live per-tick date — the one genuinely real per-tick timestamp is
    Pub/Sub's own `publishTime`, assigned at publish time, which this
    function parses instead.

    Falls back to the current UTC date if `publish_time` fails to parse.
    This is a defensive fallback, not a silent swallow of a real problem:
    a real Pub/Sub push always sets `publishTime` to a valid RFC 3339
    timestamp, so a parse failure here would itself be a symptom worth a
    caller noticing — callers of this function log the derived
    `cycle_label` unconditionally, so a fallback value is always visible
    in Cloud Logging, never hidden.
    """
    try:
        normalised = publish_time.replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(normalised)
    except ValueError:
        parsed_dt = datetime.now(tz=UTC)
    return parsed_dt.date().isoformat()


@router.post("/consolidation-nightly", status_code=status.HTTP_204_NO_CONTENT)
async def receive_consolidation_nightly(
    envelope: PubSubPushEnvelope,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Receives the Phase 14 nightly Memory Consolidation Cloud Scheduler
    tick (ADR-021 Decision 3).

    Target of the `gharos-consolidation-nightly` topic's push subscription
    (`infra/pubsub_topics.sh`), fed by the `gharos-consolidation-nightly`
    Cloud Scheduler job (`infra/scheduler_jobs.sh`) on a genuinely
    off-peak cadence. Same envelope shape and push-auth verification as
    `receive_heartbeat`/`receive_followup_sweep` above.

    Validates the decoded payload's own `job_name` matches this route's
    expected job — defense in depth against a topic/subscription
    miswiring sending the wrong tick here, matching this project's
    fail-closed posture (Phase 5's expiry-never-auto-approves, Phase 12's
    deny-by-default `ScopedGraphReader`) — and derives `cycle_label` from
    the envelope's own `publishTime` (`_derive_consolidation_cycle_label`),
    never from the static message body.

    Unlike `receive_followup_sweep`, this route actually invokes the
    consolidation service (`invoke_nightly_consolidation`) rather than
    only logging receipt, because the upstream dependency it needs
    (`app.graph.consolidation_service.run_nightly_consolidation`, E1) is
    real, parallel Phase 14 work rather than a not-yet-landed later-phase
    contract.

    Raises:
        HTTPException: 400 if the payload's `job_name` does not match
            `gharos-consolidation-nightly`.
    """
    verify_push_request(authorization=authorization, settings=settings)
    payload = _decode_message_data(envelope.message)
    job_name = payload.get("job_name") if isinstance(payload, dict) else None
    if job_name != _CONSOLIDATION_NIGHTLY_JOB_NAME:
        logger.warning(
            "consolidation_nightly_job_name_mismatch",
            got=job_name,
            expected=_CONSOLIDATION_NIGHTLY_JOB_NAME,
            message_id=envelope.message.message_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unexpected job_name for /events/consolidation-nightly: {job_name!r}",
        )

    cycle_label = _derive_consolidation_cycle_label(envelope.message.publish_time)
    logger.info(
        "consolidation_nightly_tick_received",
        message_id=envelope.message.message_id,
        publish_time=envelope.message.publish_time,
        subscription=envelope.subscription,
        cycle_label=cycle_label,
    )
    summary = invoke_nightly_consolidation(cycle_label)
    logger.info(
        "consolidation_nightly_completed",
        message_id=envelope.message.message_id,
        cycle_label=cycle_label,
        summary=str(summary),
    )

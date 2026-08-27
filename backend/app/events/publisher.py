"""`EventPublisher` — the outbound half of GharOS's Pub/Sub plumbing.

Phase 2 proved the Scheduler -> Pub/Sub -> Cloud Run round trip live in one
direction (`infra/scheduler_jobs.sh` publishes, `app.api.pubsub_receiver`
receives). This module is the first piece of *this codebase's own* code
publishing onto a topic — needed by A31 Follow-up/Persistence
(`followup_dispatcher.py`) to hand a "re-contact this open item" decision
onward to whatever downstream drafting/composing agent consumes it, without
A31 itself holding any communication tool (its own tools list is empty per
the roster — it decides and routes, nothing else).

Mirrors `app.persistence.firestore_client.create_firestore_client`'s
established shape: a small, dependency-injected factory function, no
module-level singleton, the concrete GCP client reads `PUBSUB_EMULATOR_HOST`
itself so local/emulator development needs no special-casing here.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import structlog

# `google-cloud-pubsub` (unlike `google-cloud-firestore`, already imported
# untyped-free elsewhere in this codebase) ships no `py.typed` marker, so
# mypy --strict has no stub coverage for it at all — a real library gap,
# not a stub this module could reasonably author itself. Narrow, justified
# ignore on the one import line that needs it, matching this codebase's
# established convention for a real interop gap (see
# `app.api.pubsub_receiver`'s identical rationale for `google.oauth2.
# id_token.verify_oauth2_token`).
from google.cloud import pubsub_v1  # type: ignore[import-untyped,attr-defined]

from app.settings import Settings

logger = structlog.get_logger(__name__)

_LOCAL_FALLBACK_PROJECT_ID = "gharos-local"
"""Same fallback `app.persistence.firestore_client` uses — only reached
when `Settings.gcp_project_id` is unset *and* `PUBSUB_EMULATOR_HOST` is
set (local/emulator dev), never against a real deployment."""


class EventPublisher(Protocol):
    """The minimal seam A31 (and any future publisher) needs — deliberately
    narrower than the full `google.cloud.pubsub_v1.PublisherClient` surface
    so a test double can satisfy it with a plain in-memory list."""

    def publish(self, *, topic: str, payload: dict[str, str]) -> str:
        """Publishes `payload` (JSON-encoded) onto `topic`.

        Returns:
            The publisher's message id.
        """
        ...


class GooglePubSubPublisher:
    """Real `EventPublisher` — wraps `google.cloud.pubsub_v1.PublisherClient`.
    Constructed via `create_pubsub_publisher` below; never instantiated at
    module scope (gharos-standards: no module-level singleton holding I/O).
    """

    def __init__(self, *, client: pubsub_v1.PublisherClient, project_id: str, topic_prefix: str) -> None:
        self._client = client
        self._project_id = project_id
        self._topic_prefix = topic_prefix

    def publish(self, *, topic: str, payload: dict[str, str]) -> str:
        full_topic = topic if topic.startswith(self._topic_prefix) else f"{self._topic_prefix}{topic}"
        topic_path = self._client.topic_path(self._project_id, full_topic)
        data = json.dumps(payload).encode("utf-8")
        future = self._client.publish(topic_path, data)
        message_id: str = future.result(timeout=30)
        logger.info("events.publisher.published", topic=full_topic, message_id=message_id)
        return message_id


def create_pubsub_publisher(settings: Settings) -> GooglePubSubPublisher:
    """Builds a `GooglePubSubPublisher` from typed settings, mirroring
    `app.persistence.firestore_client.create_firestore_client`'s exact
    project-id-resolution rule: real `gcp_project_id` against real Pub/Sub,
    a stable local fallback only when the emulator env var is set.
    """
    project_id = settings.gcp_project_id
    if not project_id:
        if os.environ.get("PUBSUB_EMULATOR_HOST"):
            project_id = _LOCAL_FALLBACK_PROJECT_ID
        else:
            raise ValueError(
                "gcp_project_id is unset and PUBSUB_EMULATOR_HOST is not set — "
                "refusing to guess a project id against real Pub/Sub"
            )
    client = pubsub_v1.PublisherClient()
    return GooglePubSubPublisher(
        client=client, project_id=project_id, topic_prefix=settings.pubsub_topic_prefix
    )


__all__ = ["EventPublisher", "GooglePubSubPublisher", "create_pubsub_publisher"]

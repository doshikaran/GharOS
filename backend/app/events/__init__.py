"""`backend/app/events/` — E3-owned Pub/Sub publishing and scheduled-cycle
handler logic (PHASES.md Phase 7: "A31 Follow-up / Persistence on Cloud
Scheduler").

Distinct from `backend/app/adapters/`: adapters normalise *inbound* raw
signals into `NormalizedIntake` (spec §17); this package is the *outbound*
half of the Scheduler -> Pub/Sub -> Cloud Run round trip Phase 2 proved
live (`infra/scheduler_jobs.sh`, `infra/pubsub_topics.sh`,
`app.api.pubsub_receiver`) — publishing follow-up-trigger events onward,
and the deterministic scan logic that decides when a stale open item needs
one.
"""

from __future__ import annotations

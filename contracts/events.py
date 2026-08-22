"""GharOS — frozen Pub/Sub event envelope contracts.

Owned exclusively by the CTO. Every inbound signal — email, document
upload, SMS, WhatsApp export, voice utterance, or a Cloud Scheduler tick —
enters the same Pub/Sub topic shape (spec §6.1), so the intake layer has
exactly one envelope format to parse regardless of channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    """Ingestion adapters (spec §17)."""

    EMAIL = "email"
    DOCUMENT_UPLOAD = "document_upload"
    SMS_UPI_ALERT = "sms_upi_alert"
    WHATSAPP = "whatsapp"
    PORTAL_NOTIFICATION = "portal_notification"
    VOICE_TELEPHONY = "voice_telephony"
    VOICE_HOUSEHOLD = "voice_household"
    SCHEDULED_TICK = "scheduled_tick"
    MANUAL_INTENTION = "manual_intention"


@dataclass(frozen=True, slots=True)
class InboundEnvelope:
    """The Pub/Sub message payload for every inbound signal. Published by
    an adapter in `backend/app/adapters/` (E3), consumed by the Intake
    Router (A2, E2)."""

    envelope_id: str
    channel: Channel
    received_at: datetime
    raw_payload_ref: str
    """Pointer to the raw payload in blob storage / inline small payloads —
    concrete storage strategy is E1's call in `backend/app/persistence/`."""
    household_id: str
    """Single-household framing (spec §3.1 track discipline) — this field
    exists for future multi-household support but every Phase-0-through-15
    deployment MUST use exactly one value for it. No agent registry, no
    cross-household discovery."""
    metadata: dict[str, str] = field(default_factory=dict)


class SubsystemName(str, Enum):
    """Routing targets from the primary loop (spec §6.1)."""

    CONSEQUENCE_ENGINE = "consequence_engine"
    FAIR_ALLOCATOR = "fair_allocator"
    INTENTION_ACTION = "intention_action"
    HOUSEHOLD_LEDGER = "household_ledger"
    SIMULATOR = "simulator"
    COUNCIL = "council"
    OUTBOUND_CONCIERGE = "outbound_concierge"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """A2 Intake Router's output: which subsystem(s) a normalised event
    should reach. More than one subsystem may claim an event (e.g. a
    receipt triggers both Ledger reconciliation and Consequence Engine
    warranty-obligation derivation, spec §5.4.2) — A1 Priority Arbiter
    resolves ordering when they contend for the same resources."""

    source_document_id: str
    targets: tuple[SubsystemName, ...]
    relevance_score: float


@dataclass(frozen=True, slots=True)
class ScheduledTickPayload:
    """Cloud Scheduler → Pub/Sub payload for recurring cycles (spec §6.1,
    §20): monthly salary/dues cycles, off-peak consolidation, follow-up
    cadence, call retries."""

    job_name: str
    scheduled_for: datetime
    cycle_label: str
    """e.g. '2026-08' for a monthly payroll cycle — feeds directly into
    IdempotencyKey.cycle in contracts/actions.py."""

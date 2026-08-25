"""GharOS — frozen tool protocols and permission tiers.

Owned exclusively by the CTO. Defines the permission scoping (spec §16)
that is the architectural argument for the 30% "secure tool isolation"
weight. No Firestore/FastAPI/ADK import belongs here — concrete tool
implementations live in `backend/app/tools/` (E3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Protocol, runtime_checkable

from contracts.actions import ActionResult


class PermissionTier(str, Enum):
    """T0-T6 plus T5i (spec §16.1). A tool declares exactly one tier; an
    agent's registered toolset is checked against its permitted tiers at
    registration time (PHASES.md Phase 5, Gate 5: 'a reasoning agent
    cannot invoke T4/T5/T6 — proven by test, not review')."""

    T0_READ = "T0"
    """Graph read, documents, statements. Any reasoning agent, subgraph-scoped."""
    T1_SEARCH = "T1"
    """External research, business hours, provider discovery, merchant terms."""
    T2_DRAFT = "T2"
    """Compose messages, forms, claims, briefs. No send."""
    T3_INTERNAL_WRITE = "T3"
    """Graph writes, calendar entries. Writer agents only."""
    T4_EXTERNAL_COMMUNICATION = "T4"
    """Send messages outside the household. Approval Gate only."""
    T5_VOICE_OUTBOUND = "T5"
    """Place outbound calls. Approval Gate only, within authorised bounds."""
    T5I_VOICE_INBOUND = "T5i"
    """ASR/TTS/speaker-ID for household interaction. Confers NO action
    capability of its own (safety invariant #8)."""
    T6_FINANCIAL = "T6"
    """Execute payment, pause/cancel mandate. Approval Gate only, after
    explicit human approval."""


GATED_TIERS: frozenset[PermissionTier] = frozenset(
    {
        PermissionTier.T4_EXTERNAL_COMMUNICATION,
        PermissionTier.T5_VOICE_OUTBOUND,
        PermissionTier.T6_FINANCIAL,
    }
)
"""T4, T5, T6 are reachable ONLY through the Approval Gate (spec §16.3 rule
2). A tool registration for one of these tiers outside the Approval Gate's
own module is a defect — Gate 5 requires a test proving this, not a review
comment."""

MONEY_ANALYSIS_TIER = PermissionTier.T0_READ
"""Placeholder name for readability at call sites that check invariant #1
('no agent holds both money-analysis (T0) and financial (T6) capability').
The actual check is: an agent registered with T6 must not also read the
Ledger subgraph read-tools reserved for reasoning-only agents like A28
Reconciliation — enforced by E3's tool registry, not by this constant
alone."""


@runtime_checkable
class Tool(Protocol):
    """Structural protocol every simple, non-idempotent (T0-T2) tool
    satisfies. Concrete tools live in `backend/app/tools/` (E3), organised
    by tier per spec §16.2."""

    name: str
    tier: PermissionTier

    def invoke(self, **kwargs: object) -> ActionResult[object]:
        """Must never raise an uncaught exception that masks failure as
        success, and must never return ActionResult.success on a failed
        underlying call (safety invariant #7)."""
        ...


@runtime_checkable
class Registrable(Protocol):
    """The minimal shape shared infrastructure that only ever needs
    identity + tier (chiefly `ToolRegistry`, `backend/app/tools/registry.py`
    — E3) can rely on, satisfied by BOTH `Tool` (T0-T2, simple `invoke`)
    and `IdempotentTool`/`ApprovalGatedTool` (T3-T6, `invoke_idempotent`).
    Deliberately narrower than `Tool`: a registry that only ever reads
    `.name`/`.tier` and hands the tool back to a caller who already knows
    which family it belongs to (and therefore which invoke method to call)
    has no business requiring the full `Tool` shape from every tool it
    holds. Added Phase 5, once a single registry needed to hold both
    families side by side (T0 read tools and T3 write tools, in the same
    agent's toolset) and typing it as `Tool` alone rejected every
    `IdempotentTool` at the type checker, even though the registry's own
    logic never touched `.invoke()`."""

    name: str
    tier: PermissionTier


class IdempotentTool(ABC):
    """Base for any T3+ tool. `invoke_idempotent` MUST be used instead of a
    raw `invoke` for T3 and above — spec §19.1: replays are no-ops
    returning the original result, enforced at the tool level, not the
    agent level.

    Deliberately does NOT inherit from `Tool` (it has no `invoke` method —
    `invoke_idempotent` replaces it, it does not implement it) but DOES
    declare `name`, matching `Tool.name`, so that shared infrastructure
    which only needs identity + tier (e.g. `ToolRegistry`, which never
    calls `.invoke()` on anything it holds — see `contracts.tools.
    Registrable` below) can accept either family uniformly without forcing
    an idempotency-keyed tool to pretend it has a non-idempotent `invoke`
    it must never expose. Added Phase 5 alongside `Registrable`, once real
    T3+ tools (`backend/app/tools/`) needed to be held in the same registry
    as T0 `Tool`s and this gap surfaced as a real static-typing failure,
    not a hypothetical one."""

    name: str
    tier: PermissionTier

    @abstractmethod
    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        raise NotImplementedError


class ApprovalGatedTool(IdempotentTool):
    """Base for T4/T5/T6 tools. `backend/app/arbitration/` (E3, CTO-
    adjudicated per PHASES.md repo structure) is the only caller permitted
    to construct and invoke one of these — enforced by not exposing this
    class (or its subclasses) to `backend/app/agents/` at all; E2's agents
    hold no import path to this module's gated subclasses. This is the
    concrete mechanism behind 'reasoning agents hold no action
    credentials.'"""

    tier: PermissionTier  # narrowed to a member of GATED_TIERS by subclasses
    bounds: dict[str, object]
    """Authorised bounds this invocation may not exceed (date range, price
    ceiling, disclosable facts, must-not-answer list — spec §13.3). An
    out-of-bounds request raises contracts.errors.OutOfBounds, never a
    guess."""


class ReadOnlyTool(Tool, Protocol):
    """Marker protocol for T0 tools. The Reconciliation Agent (A28) is
    registered with ONLY tools satisfying this protocol — spec §10.5: 'the
    Reconciliation Agent is structurally incapable of moving money.' A
    registry that hands A28 anything outside this protocol is a defect."""

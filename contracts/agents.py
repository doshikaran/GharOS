"""GharOS — frozen agent I/O contracts.

Owned exclusively by the CTO. Every one of the 69 agents in spec §15 has
one responsibility, an explicit input contract, an explicit output
contract, and an explicit forbidden list. This module defines the generic
envelope shape every agent invocation uses; each concrete agent's specific
input/output payload types are defined by E2 in `backend/app/agents/`, but
MUST be built on top of `AgentInput`/`AgentOutput` below so that
orchestration, tracing, and confidence handling are uniform across all 69.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from contracts.graph_types import AgentId, Derivation


class ModelTier(str, Enum):
    """Cost discipline enforced in code (spec §21.1, PHASES.md §6.2.3):
    Flash for high-volume ingestion/normalization/routing/classification;
    Pro-tier reserved for the named hard reasoning steps. A Pro-tier call
    from an agent not on `backend/app/reasoning/model_router.py`'s
    allowlist is a test failure."""

    FLASH = "flash"
    PRO = "pro"
    DETERMINISTIC = "deterministic"
    """Not an LLM call at all — a code tool (fairness solver, mechanism
    arbiter, salary calculator, etc.). Modeled as a tier here so agent
    tracing is uniform even for agents whose 'reasoning' is fully
    deterministic (spec §16.2)."""


@dataclass(frozen=True, slots=True)
class AgentInput:
    """Generic envelope every agent receives. Concrete agents extend this
    with their own typed payload (e.g. the Implication Agent's input adds
    the extraction record + household context) but every agent has at
    least this much."""

    invocation_id: str
    agent_id: AgentId
    household_id: str
    triggered_by: str
    """A SourceDocument id, another agent's output id, or a scheduled tick id."""
    context_refs: tuple[str, ...]
    """Node/edge ids the agent is entitled to read — enforces subgraph
    scoping for agents like the Council specialists (spec §12.2)."""


@dataclass(frozen=True, slots=True)
class Citation:
    """A pointer from a claim back to the exact evidence supporting it.
    Mandatory for every IMPLIED obligation the Implication Agent (A12)
    produces (spec §7.6: 'every implies edge must cite a source span;
    uncitable → discarded'), and for every claim a Council specialist or
    Simulator branch makes."""

    source_document_id: str
    region: str
    supports_claim: str
    """Short restatement of exactly what this citation is claimed to
    support — used by adversarial tests (gharos-standards skill) asserting
    the citation actually supports the claim, not just that one exists."""


@dataclass(frozen=True, slots=True)
class AgentOutput:
    """Generic envelope every agent returns. `citations` is empty only for
    agents whose output is not itself a claim requiring evidence (e.g. A1
    Priority Arbiter's scheduling decision) — the CTO gate review checks
    this per-agent, not globally."""

    invocation_id: str
    agent_id: AgentId
    model_tier: ModelTier
    prompt_version: str
    """Which version of this agent's prompt (backend/app/prompts/, E2-owned,
    versioned per ADR-003) produced this output — required for the full
    invocation trace spec §22 demands ('every agent invocation traced:
    inputs consulted, outputs produced, model tier, confidence, latency').
    'deterministic' for ModelTier.DETERMINISTIC agents with no prompt."""
    confidence: float
    derivation: Derivation
    citations: tuple[Citation, ...]
    produced_at: datetime
    forbidden_violations: tuple[str, ...] = field(default_factory=tuple)
    """Populated only by test harnesses / adversarial evaluation runs
    asserting an agent did NOT do something on its forbidden list (e.g.
    A28 Reconciliation attempting a write). Empty in normal operation —
    a non-empty tuple reaching production code is itself a defect."""

"""GharOS agent layer — owned exclusively by E2 (Agents & Reasoning).

Home for the ADK orchestration layer and, from Phase 3 onward, all 69
agents in `GharOS_Build_Spec_v2.md` §15 (`gharos-agent-roster` skill has
the full roster). Phase 2 (PHASES.md "PHASE 2 — MANDATORY STACK PROOF")
introduces this package with `agents.base` (the shared ADK
agent-construction pattern) and `agents.orchestration.stack_proof_agent`
(a trivial, genuine ADK agent + tool call, proving the framework works —
Gate 2 requirement 2) — deliberately structured so every later roster
agent follows the same construction pattern rather than each phase
inventing its own.

Reasoning agents built here never hold action credentials: no module in
this package may import `contracts.tools.ApprovalGatedTool` or any of its
subclasses (safety invariants #1 and #5) — they propose, tools (E3-owned,
`backend/app/tools/`) act.

Typed errors for this layer live in `agents.errors`, not `contracts.errors`
(frozen, CTO-only) or `reasoning.errors` (scoped to model-routing/call
failures, a different failure surface — see `agents.errors` docstring).
"""

from __future__ import annotations

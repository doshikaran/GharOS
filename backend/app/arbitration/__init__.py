"""`backend/app/arbitration/` — the arbitration, approval, and action layer
(PHASES.md Phase 5, spec §15.12, §16.3, §18).

This package is the sole home of:

- **A57 Confidence Arbiter** (`confidence_arbiter.py`) — the only code path
  permitted to decide that a proposed action should execute, be approved,
  be escalated, or be discarded (spec §15.12: "the only path to action").
- **The Approval Gate** (`approval_gate.py`) — a service, not an LLM agent
  (spec §15.12) — assembles evidence bundles, writes `ApprovalRequest`/
  `ActionRecord` graph nodes, and is the only caller that constructs and
  executes a `contracts.tools.ApprovalGatedTool` (T4/T5/T6).
- **A58 Escalation Agent** (`escalation_agent.py`) — routes an escalation
  to a real household member.
- **Concrete `contracts.actions.Action` implementations** (`actions.py`)
  and the one reference `contracts.tools.ApprovalGatedTool` subclass
  (`gated_tool.py`) that proves the base class is real and enforced.

**Structural invariant this whole package exists to hold:** no module
under `backend/app/agents/` imports anything from this package, and no
`Action` subclass defined in `actions.py` is constructed anywhere outside
it — proven in `backend/tests/test_action_construction_boundary.py`, not
asserted in a comment. `contracts.tools.ApprovalGatedTool`'s own docstring
names this exact directory (`backend/app/arbitration/`) as "the only
caller permitted to construct and invoke" a T4/T5/T6 tool.
"""

from __future__ import annotations

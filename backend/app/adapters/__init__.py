"""GharOS backend — external-world adapters (E3-owned, per gharos-standards
file-ownership table).

Every module here wraps one external API behind a small, dependency-
injected class or function — never a module-level singleton holding I/O
(gharos-standards: "no module-level singletons"). Reasoning agents under
`backend/app/agents/` (E2-owned) never import a concrete client library
directly; they receive an adapter instance constructed at the composition
root (`backend/app/main.py`, or a test fixture).

Phase 2 adds `secret_manager` (Secret Manager wiring, PHASES.md Phase 2
work item 4). Later phases add the ingestion-channel adapters (email,
document upload, SMS/UPI, WhatsApp export — spec §17).
"""

from __future__ import annotations

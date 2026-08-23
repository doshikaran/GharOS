"""GharOS backend — external-world adapters (E3-owned, per gharos-standards
file-ownership table).

Every module here wraps one external API behind a small, dependency-
injected class or function — never a module-level singleton holding I/O
(gharos-standards: "no module-level singletons"). Reasoning agents under
`backend/app/agents/` (E2-owned) never import a concrete client library
directly; they receive an adapter instance constructed at the composition
root (`backend/app/main.py`, or a test fixture).

Phase 2 added `secret_manager` (Secret Manager wiring, PHASES.md Phase 2
work item 4). Phase 3 adds:

- `ingestion` — the shared `IngestionAdapter` Protocol, `RawIntakePayload`,
  and `NormalizedIntake` shapes every channel adapter below builds on.
- `email_adapter`, `document_upload_adapter`, `chat_export_adapter`,
  `sms_adapter` — the four channel adapters spec §17 names for this phase.
- `document_type_ids`, `document_type_specs`, `document_registry` — the
  Document-Type Registry (spec §5.4): the fourteen canonical `type_id`
  strings, the fourteen declarative `DocumentTypeSpec` data entries, and
  `DocumentTypeRegistry` itself (open strategy-pattern registry; E2
  registers each type's `ExtractionStrategy` into it next).
- `registry_gap_log` — the structured-logging-backed, queryable
  registry-gap mechanism (spec §5.4.3 rule 4) A2 Intake Router (E2) calls
  when a document doesn't match any registered type.
"""

from __future__ import annotations

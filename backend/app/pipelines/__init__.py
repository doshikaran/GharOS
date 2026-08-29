"""`backend/app/pipelines/` — connective orchestration over adapters +
agents + the document-type registry (ADR-023 §6, added Phase 14.5, E3).

Currently one module: `ingestion_orchestrator`, the single wire from a
`RawIntakePayload` to committed graph nodes (DEBT-009's repayment).
"""

from __future__ import annotations

from .ingestion_orchestrator import IngestionOrchestrator

__all__ = ["IngestionOrchestrator"]

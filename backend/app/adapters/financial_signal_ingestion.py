"""A27 — Financial Signal Ingestion (spec §5.4.2, §10.3.A, PHASES.md Phase 7).

*Responsibility:* "Normalize financial signals to LEDGER_EVENTs."
*Model tier:* Flash; Pro-tier multimodal for handwritten registers and
degraded scans.
*Forbidden:* reconciliation judgment, action.

## What this module is — and, just as important, what it is NOT (read this
## before touching anything else in this file)

Phase 3 already built real, working `ExtractionStrategy` implementations for
every financial document type (`app.agents.intake.strategies.
bank_statement_strategy`, `.upi_sms_alert_strategy`, `.receipt_strategy`,
`.society_notice_strategy`, `.utility_bill_strategy` — all five produce
`contracts.graph_types.LedgerEvent` nodes inside their `GraphMappingResult`,
per `contracts.graph_types.ExtractionStrategy.map_to_graph`'s own contract).
**A27 is not a second extraction pipeline** — building one would duplicate
Phase 3's real, tested work and violate ADR-008's strategy pattern (one
extractor per document type, registered once). Two things Phase 3 did not
build, because they only become a problem once financial documents actually
arrive from more than one channel about the *same* real-world transaction,
are what this module is:

1. **Cross-channel deduplication.** The same real payment is routinely
   reported twice: a UPI SMS alert lands the moment the debit clears, and
   the same transaction reappears days later as one row in a bank
   statement. Both strategies above run independently and neither has
   access to the other's output (`ExtractionStrategy.map_to_graph` receives
   only `extracted_fields` — no `GraphReader`, ADR-008) — nothing upstream
   of this module would ever notice the two `LedgerEvent`s describe the
   same debit. Left alone, that is two `LedgerEvent`s in the graph for one
   real rupee movement, and every downstream consumer (A28 Reconciliation's
   spend totals, the recovered-money counter) silently doubles it.
2. **Idempotent persistence of what the strategies already computed.**
   `GraphMappingResult` is data — "strategies return data; only
   `GraphWriter`, via the writer-agent pipeline, ever touches Firestore"
   (`contracts.graph_types.GraphMappingResult`'s own docstring). Something
   has to actually call `GraphWriter` for the `LedgerEvent` nodes and their
   edges, exactly once per real underlying transaction even if the same
   source document is re-ingested (a re-uploaded statement, a retried
   Pub/Sub delivery) — the T3 writer-agent counterpart to `app.agents.
   consequence.obligation_writer.ObligationWriter` (A15), but for
   LEDGER_EVENTs instead of OBLIGATIONs.

**"Pro-tier multimodal for handwritten registers and degraded scans" needs
no code here.** `app.agents.intake.document_extraction.
DocumentExtractionAgent` (A3) already escalates every document type — not
just financial ones — to `ModelTier.PRO` automatically whenever its own
Flash pass reports `degraded_input_observed` (two-pass design, spec
§15.2). That escalation is generic across all fourteen document types by
construction; a financial-signal-specific escalation path would be a
second, redundant implementation of something A3 already does correctly.

**Forbidden, structurally, by what this module simply does not do:** no
series matching, no silent-price-hike detection, no duplicate-*charge*
detection (a merchant billing twice for one real purchase — a judgment call
about the *merchant's* error, A28's job), no dues reconciliation, no salary
computation, and no write of anything other than `LedgerEvent` nodes plus
the edges the originating strategy already computed. The cross-channel
matching below is deliberately coarse and mechanical (exact-currency,
near-exact amount, a same-day-or-adjacent occurrence window, a normalised
counterparty-string comparison) — matching, not reconciling: it never
decides whether a charge is *legitimate*, only whether two already-written
records plausibly describe the *same* underlying event.

## A known, honest limitation (raise-worthy, not worked around)

Real cross-channel dedup ideally checks a *newly ingested* event against
every `LedgerEvent` already sitting in the graph. `contracts.repositories.
GraphReader` (frozen) has no such primitive — `series()` needs a known
`RECURRING_COMMITMENT` id, `spend_by_category()` returns aggregated floats,
not raw events, and there is nothing resembling "LedgerEvents in this date
window." So this module's dedup only ever sees what its caller passes it
directly: the current ingestion batch's own `GraphMappingResult`s, plus
whatever `existing_events` the caller already happens to have on hand (e.g.
a reconciliation-adjacent agent that queried `series()` for the specific
commitment this batch is thought to belong to). A full "check this new
event against the whole recent ledger" primitive does not exist on the
frozen contract today — this is a real gap worth raising to the CTO for a
future `GraphReader` addition, not something to fake with an unauthorised
read path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import structlog
from contracts.graph_types import Edge, GraphMappingResult, LedgerEvent, NodeId

from app.tools.graph_write_tool import GraphWriteTool

logger = structlog.get_logger(__name__)

_AGENT_ID = "A27"

_SAME_EVENT_AMOUNT_TOLERANCE = 0.01
"""Absolute currency-unit tolerance for "the same amount" — covers the rare
paisa-level rounding difference between an SMS alert's rounded figure and a
statement's exact posted amount, nothing looser."""
_SAME_EVENT_OCCURRENCE_WINDOW = timedelta(days=3)
"""A UPI SMS alert fires the moment a debit clears; the same debit can post
to a bank statement up to a few days later (settlement lag). Wider than
same-day on purpose, narrow enough that it does not start matching genuinely
different transactions a few days apart."""
_COUNTERPARTY_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
_COUNTERPARTY_SIMILARITY_FLOOR = 0.5
"""Minimum token-Jaccard similarity between two `counterparty_raw` strings
to be considered "the same counterparty" for dedup purposes — deliberately
permissive (an SMS's terse VPA string and a statement's fuller merchant
name rarely tokenize identically) but never zero: an empty overlap is never
treated as a match."""


def _counterparty_tokens(raw: str) -> frozenset[str]:
    return frozenset(_COUNTERPARTY_TOKEN_PATTERN.findall(raw.lower()))


def _counterparty_similarity(a: str, b: str) -> float:
    tokens_a, tokens_b = _counterparty_tokens(a), _counterparty_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _is_same_underlying_event(candidate: LedgerEvent, existing: LedgerEvent) -> bool:
    """Mechanical, deterministic matching only — see module docstring's
    "Forbidden" section. Never a model call, never a judgment about
    legitimacy."""
    if candidate.kind is not existing.kind:
        return False
    if candidate.currency != existing.currency:
        return False
    if abs(candidate.amount - existing.amount) > _SAME_EVENT_AMOUNT_TOLERANCE:
        return False
    if abs(candidate.occurred_at - existing.occurred_at) > _SAME_EVENT_OCCURRENCE_WINDOW:
        return False
    return _counterparty_similarity(candidate.counterparty_raw, existing.counterparty_raw) >= (
        _COUNTERPARTY_SIMILARITY_FLOOR
    )


def _natural_idempotency_key(event: LedgerEvent) -> str:
    """A deterministic, content-derived idempotency key for *replaying the
    same extraction* (re-processing the same source document) — distinct
    from the cross-channel dedup above, which handles *two different*
    source documents describing the same real event. Built from the
    event's own `Provenance.source_ref` (the same source document + region
    always yields the same key), never from the strategy-minted random
    `NodeId` (which is fresh, and therefore useless as a replay key, on
    every extraction run including a genuine re-run of the same document).
    """
    source_ref = event.provenance.source_ref
    if source_ref is not None:
        basis = f"{source_ref.source_document_id}:{source_ref.region}"
    else:
        # AMBIGUOUS-with-no-source-ref is a real, allowed provenance shape
        # (contracts.graph_types.Provenance) — fall back to the event's own
        # natural key. Coarser (see module docstring's amount/date collision
        # caveat) but never crashes, and still real replay-safety for the
        # common case of literally re-running the same batch.
        basis = (
            f"{event.kind.value}:{event.amount:.2f}:{event.currency}:"
            f"{event.occurred_at.date().isoformat()}:{event.counterparty_raw.strip().lower()}"
        )
    return f"ledger_event_ingest:{basis}"


@dataclass(frozen=True, slots=True)
class LedgerIngestOutcome:
    """One `LedgerEvent` candidate's disposition — every candidate produces
    exactly one of these, so a caller can account for every event Phase 3's
    strategies handed this module (mirrors `app.agents.consequence.
    obligation_writer.WriteOutcome`'s established shape for the same
    reason: nothing is silently dropped)."""

    node_id: NodeId
    action: Literal["written", "deduplicated"]
    detail: str


class FinancialSignalIngestor:
    """A27. Dependency-injected on the real T3 `GraphWriteTool` — never a
    raw `GraphWriter`, so every write this module performs is
    idempotency-keyed and provenance-guarded by construction (the same
    machinery Gate 5 already proved, reused rather than re-implemented).
    """

    def __init__(self, *, graph_write_tool: GraphWriteTool) -> None:
        self._graph_write_tool = graph_write_tool

    def ingest(
        self,
        *,
        mapping_results: tuple[GraphMappingResult, ...],
        existing_events: tuple[LedgerEvent, ...] = (),
    ) -> tuple[LedgerIngestOutcome, ...]:
        """Persists every `LedgerEvent` across `mapping_results`, exactly
        once per real underlying transaction.

        Args:
            mapping_results: one or more already-computed
                `GraphMappingResult`s from a financial document type's
                `ExtractionStrategy.map_to_graph()` (bank statement, UPI/
                SMS alert, receipt, society notice, utility bill) — this
                batch may span more than one source document (e.g. an SMS
                alert and, days later, the statement that confirms it),
                which is exactly the case cross-channel dedup exists for.
            existing_events: previously-persisted `LedgerEvent`s the
                caller already has on hand to dedupe newly-ingested events
                against (see module docstring's `GraphReader` limitation
                note — this module cannot fetch these itself).

        Returns:
            One `LedgerIngestOutcome` per `LedgerEvent` candidate found
            across `mapping_results`, in encounter order.
        """
        seen: list[LedgerEvent] = list(existing_events)
        outcomes: list[LedgerIngestOutcome] = []

        for result in mapping_results:
            ledger_events = [node for node in result.nodes if isinstance(node, LedgerEvent)]
            edges_by_from_id: dict[NodeId, list[Edge]] = {}
            for edge in result.edges:
                edges_by_from_id.setdefault(edge.from_id, []).append(edge)

            for candidate in ledger_events:
                match = next(
                    (existing for existing in seen if _is_same_underlying_event(candidate, existing)), None
                )
                if match is not None:
                    outcomes.append(
                        LedgerIngestOutcome(
                            node_id=match.id,
                            action="deduplicated",
                            detail=(
                                f"matches already-recorded {match.kind.value} of {match.amount} "
                                f"{match.currency} on {match.occurred_at.date().isoformat()} "
                                f"({match.id}) — same underlying transaction, not written again"
                            ),
                        )
                    )
                    logger.info(
                        "adapters.financial_signal_ingestion.a27.deduplicated",
                        candidate_counterparty=candidate.counterparty_raw,
                        matched_node_id=str(match.id),
                    )
                    continue

                idempotency_key = _natural_idempotency_key(candidate)
                write_result = self._graph_write_tool.invoke_idempotent(
                    idempotency_key, operation="write_node", node=candidate
                )
                written_node_id = NodeId(str(write_result.value))
                for edge in edges_by_from_id.get(candidate.id, ()):
                    edge_key = (
                        f"ledger_event_ingest_edge:{idempotency_key}:{edge.edge_type.value}:{edge.to_id}"
                    )
                    self._graph_write_tool.invoke_idempotent(edge_key, operation="write_edge", edge=edge)

                seen.append(candidate)
                outcomes.append(
                    LedgerIngestOutcome(
                        node_id=written_node_id,
                        action="written",
                        detail=f"new {candidate.kind.value} of {candidate.amount} {candidate.currency}",
                    )
                )
                logger.info(
                    "adapters.financial_signal_ingestion.a27.written",
                    node_id=str(written_node_id),
                    kind=candidate.kind.value,
                    amount=candidate.amount,
                )

        return tuple(outcomes)


__all__ = ["FinancialSignalIngestor", "LedgerIngestOutcome"]

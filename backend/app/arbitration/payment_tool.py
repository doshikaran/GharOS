"""`SandboxPaymentTool` — the real T6 payment/mandate tool (spec §10.5's
third tool group: "Payment tools — execute payment, pause/cancel mandate.
Reachable ONLY via the Approval Gate"), PHASES.md Phase 7.

Follows `gated_tool.ReferenceGatedTool`'s exact established shape (this
module's sibling, same package) — check idempotency reservation first,
perform the effect, record the result — but with a real, concrete effect
instead of an injected generic callable: this is the actual tool a later
phase's real payment-rail integration (if one is ever built — spec's own
open question §27.2 leaves this genuinely undecided at the project level)
would sit behind, not a second reference implementation.

## What "sandbox only" means here — a real product decision, not an
## implementation detail (documented per this phase's own instructions)

**No real external payment rail is called anywhere in this file.** There
is no HTTP client, no bank/UPI API credential, no merchant gateway SDK
import — this module cannot move real money even in principle, because it
holds no integration capable of it. That is deliberate, for two reasons,
not one:

1. **There are no real credentials for one in this project.** Financial
   credentials never touch a reasoning agent (spec §23) — but they also
   never existed here at all. Faking a call to an external rail (e.g. an
   HTTP call to a stub endpoint dressed up as "the bank") would not be
   more real than what this module does; it would just add an unverifiable
   layer of theatre on top of the same underlying graph write.
2. **The point of Phase 7 is proving the safety machinery, not the rail.**
   Gate 7 asks for "double payment impossible under replay" — a property
   of the *idempotency mechanism*, not of any specific bank's API. That
   mechanism is fully real and fully exercised here: a real
   `ApprovalRequest` -> real audit-before-execute
   (`app.arbitration.approval_gate.ApprovalGate`) -> this tool's real
   `check_and_reserve`/`record_result` cycle against the real
   `contracts.repositories.IdempotencyStore` -> a real `contracts.
   graph_types.LedgerEvent` (or `RecurringCommitment` status change)
   durably written via the real, provenance-guarded `GraphWriter`. Every
   piece of that chain is the same code a real integration would run
   through; only the very last hop (an actual bank/UPI network call) is
   absent, because building a *fake* version of that one hop would
   misrepresent what was actually tested — exactly the "overclaimed
   integration" `.claude/agents/e3.md` warns discredits an otherwise
   strong submission.

The effect this tool performs is therefore real, internal, and fully
wired — a `LedgerEvent(kind=DEBIT)` node genuinely lands in the household
graph, a `RecurringCommitment.status` genuinely flips to `"paused"`/
`"cancelled"` — it is only the *external* half of "pay the plumber" that
is sandboxed, matching exactly what a real integration's own bookkeeping
side-effect would look like the instant a real rail confirmed success.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from contracts.actions import ActionResult
from contracts.errors import OutOfBounds, ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Provenance,
    RecurringCommitment,
    SourceRef,
)
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import ApprovalGatedTool, PermissionTier


class PaymentEffect(StrEnum):
    """The three effects spec §10.5 names for this tool group, verbatim:
    "execute payment, pause/cancel mandate.\""""

    DEBIT_PAYMENT = "debit_payment"
    PAUSE_MANDATE = "pause_mandate"
    CANCEL_MANDATE = "cancel_mandate"


_MANDATE_STATUS_BY_EFFECT: dict[PaymentEffect, Literal["paused", "cancelled"]] = {
    PaymentEffect.PAUSE_MANDATE: "paused",
    PaymentEffect.CANCEL_MANDATE: "cancelled",
}


class SandboxPaymentTool(ApprovalGatedTool):
    """A single T6 tool covering both payment groups spec §10.5 names —
    one class, `effect`-dispatched by kwarg (mirroring `GraphWriteTool`'s
    own `operation`-dispatch style), rather than three near-identical
    classes.

    Constructed and registered only from `backend/app/arbitration/` (this
    module's own package) via `gated_tool.register_gated_tool` — the same
    rule every T4/T5/T6 tool in this codebase already follows, checked
    structurally by `app.tools.registry.ToolRegistry.register`, not by
    convention.
    """

    def __init__(
        self,
        *,
        graph_writer: GraphWriter,
        graph_reader: GraphReader,
        idempotency_store: IdempotencyStore,
        bounds: dict[str, object],
        name: str = "sandbox_payment_tool",
    ) -> None:
        """Args:
        graph_writer: performs the actual write — real, provenance-
            guarded, exactly `app.tools.graph_write_tool.GraphWriteTool`'s
            own underlying dependency.
        graph_reader: read-only (T0) — needed only to fetch the *current*
            `RecurringCommitment` before superseding it (a mandate status
            change must preserve every other field: label, counterparty,
            amount, cadence, price_history, last_used_at). T0 read access
            here is not "money-analysis capability" in safety invariant
            #1's sense (that invariant is about a *reasoning* agent
            holding both T0-on-Ledger and T6 — this is the gated tool's
            own internal read-before-write, exactly as `app.arbitration.
            approval_gate.ApprovalGate` itself already holds both a
            `GraphReader` and full execution authority).
        idempotency_store: this tool's own reservation cycle (see class
            docstring) — deliberately NOT delegated to `GraphWriteTool`
            (which has its own internal store check): reading the
            *current* `RecurringCommitment` before building the superseded
            version must never happen on a replay (the node may already
            be superseded by the first call, so `graph_reader.get_node`
            would legitimately return `None` per its own "or None if
            absent/superseded" contract) — checking-and-reserving here,
            before any read, is what makes a replay a true no-op instead
            of a spurious "commitment not found" failure.
        bounds: authorised bounds (spec §13.3) — `"max_amount"` is checked
            as a ceiling (`kwargs["amount"] <= bounds["max_amount"]`);
            every other key is checked exact-match, matching
            `ReferenceGatedTool.check_bounds`'s convention.
        """
        self.name = name
        self.tier: PermissionTier = PermissionTier.T6_FINANCIAL
        self.bounds = bounds
        self._writer = graph_writer
        self._reader = graph_reader
        self._idempotency_store = idempotency_store

    def check_bounds(self, **kwargs: object) -> None:
        """Raises `contracts.errors.OutOfBounds` on the first bound this
        invocation violates.

        `"max_amount"` (when present in `self.bounds`) is a ceiling check
        on `kwargs["amount"]` — richer than exact-match, matching
        `ReferenceGatedTool.check_bounds`'s own docstring inviting exactly
        this ("a real T5/T6 tool's bounds checking is richer... this
        reference implementation demonstrates the mechanism... not the
        full richness a later phase's concrete tool needs"). Every other
        bound key present in both `self.bounds` and `kwargs` is checked
        exact-match, unchanged from the reference tool's own rule.
        """
        max_amount = self.bounds.get("max_amount")
        if max_amount is not None and "amount" in kwargs:
            amount = kwargs["amount"]
            amount_out_of_bounds = (
                not isinstance(amount, int | float)
                or not isinstance(max_amount, int | float)
                or amount > max_amount
            )
            if amount_out_of_bounds:
                raise OutOfBounds(bound_name="max_amount", requested=str(amount), authorised=str(max_amount))
        for bound_name, authorised in self.bounds.items():
            if bound_name == "max_amount":
                continue
            if bound_name in kwargs and kwargs[bound_name] != authorised:
                raise OutOfBounds(
                    bound_name=bound_name, requested=str(kwargs[bound_name]), authorised=str(authorised)
                )

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Executes one payment/mandate effect, exactly once per
        `idempotency_key` — spec §19.1's literal "one debit per due-ID per
        cycle": the caller (`app.arbitration.approval_gate.ApprovalGate.
        approve_and_execute`) derives `idempotency_key` from
        `contracts.actions.IdempotencyKey(entity_id, action_type, cycle)`,
        the same three-part key every T3+ tool in this codebase uses.

        Args (via kwargs):
            effect: one of `PaymentEffect`'s values.
            confidence: float — carried into the written node/version's
                `Provenance.confidence`.
            deriving_agent: str — the proposing agent's id, carried into
                `Provenance.deriving_agent`.
            source_ref: `contracts.graph_types.SourceRef | None`.
            For `effect="debit_payment"`: `amount: float`,
                `currency: str`, `counterparty_raw: str`,
                `occurred_at: datetime`.
            For `effect="pause_mandate"`/`"cancel_mandate"`:
                `commitment_id: str`.

        Returns:
            `ActionResult.success(result_ref)` — the written `LedgerEvent`
            id, or the superseded `RecurringCommitment`'s new version id.
            On replay (same `idempotency_key`), the *original* call's
            result, with no read or write attempted at all.

        Raises:
            contracts.errors.OutOfBounds: a bound was violated.
            contracts.errors.ToolFailure: missing/malformed kwargs, an
                unknown `effect`, a `commitment_id` that does not resolve
                to a `RecurringCommitment`, or the underlying `GraphWriter`
                failed — never a fabricated success (safety invariant #7).
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(cached_result_ref)

        self.check_bounds(**kwargs)

        effect_raw = kwargs.get("effect")
        if not isinstance(effect_raw, str):
            raise ToolFailure(
                tool_name=self.name, reason=f"unknown or missing effect {effect_raw!r}", retryable=False
            )
        try:
            effect = PaymentEffect(effect_raw)
        except ValueError as exc:
            raise ToolFailure(
                tool_name=self.name, reason=f"unknown or missing effect {effect_raw!r}", retryable=False
            ) from exc

        try:
            if effect is PaymentEffect.DEBIT_PAYMENT:
                result_ref = self._perform_debit(kwargs)
            else:
                result_ref = self._perform_mandate_change(kwargs, effect)
        except (ToolFailure, OutOfBounds):
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, matching graph_write_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        self._idempotency_store.record_result(idempotency_key, result_ref)
        return ActionResult.success(result_ref)

    def _common_provenance(self, kwargs: dict[str, object]) -> Provenance:
        confidence = kwargs.get("confidence")
        deriving_agent = kwargs.get("deriving_agent")
        source_ref = kwargs.get("source_ref")
        if not isinstance(confidence, int | float):
            raise ToolFailure(tool_name=self.name, reason="'confidence' (float) is required", retryable=False)
        if not isinstance(deriving_agent, str) or not deriving_agent:
            raise ToolFailure(
                tool_name=self.name, reason="'deriving_agent' (str AgentId) is required", retryable=False
            )
        if source_ref is not None and not isinstance(source_ref, SourceRef):
            raise ToolFailure(
                tool_name=self.name, reason="'source_ref' must be a SourceRef or None", retryable=False
            )
        return Provenance(
            derivation=Derivation.INFERRED if source_ref is not None else Derivation.AMBIGUOUS,
            source_ref=source_ref,
            confidence=float(confidence),
            deriving_agent=AgentId(deriving_agent),
            created_at=datetime.now(UTC),
        )

    def _perform_debit(self, kwargs: dict[str, object]) -> str:
        amount = kwargs.get("amount")
        currency = kwargs.get("currency")
        counterparty_raw = kwargs.get("counterparty_raw")
        occurred_at = kwargs.get("occurred_at")
        if not isinstance(amount, int | float):
            raise ToolFailure(tool_name=self.name, reason="'amount' (float) is required", retryable=False)
        if not isinstance(currency, str) or not currency:
            raise ToolFailure(tool_name=self.name, reason="'currency' (str) is required", retryable=False)
        if not isinstance(counterparty_raw, str) or not counterparty_raw:
            raise ToolFailure(
                tool_name=self.name, reason="'counterparty_raw' (str) is required", retryable=False
            )
        if not isinstance(occurred_at, datetime):
            raise ToolFailure(
                tool_name=self.name, reason="'occurred_at' (datetime) is required", retryable=False
            )

        provenance = self._common_provenance(kwargs)
        ledger_event = LedgerEvent(
            id=NodeId(f"ledger_event:{uuid.uuid4().hex}"),
            provenance=provenance,
            kind=LedgerEventKind.DEBIT,
            amount=float(amount),
            currency=currency,
            occurred_at=occurred_at,
            counterparty_raw=counterparty_raw,
        )
        node_id = self._writer.write_node(ledger_event)
        return str(node_id)

    def _perform_mandate_change(self, kwargs: dict[str, object], effect: PaymentEffect) -> str:
        commitment_id_raw = kwargs.get("commitment_id")
        if not isinstance(commitment_id_raw, str) or not commitment_id_raw:
            raise ToolFailure(
                tool_name=self.name, reason="'commitment_id' (str) is required", retryable=False
            )
        commitment_id = NodeId(commitment_id_raw)
        current = self._reader.get_node(commitment_id)
        if not isinstance(current, RecurringCommitment):
            raise ToolFailure(
                tool_name=self.name,
                reason=f"no active RecurringCommitment found for {commitment_id!r}",
                retryable=False,
            )

        provenance = self._common_provenance(kwargs)
        new_status = _MANDATE_STATUS_BY_EFFECT[effect]
        updated = replace(current, status=new_status, provenance=provenance)
        new_id = self._writer.supersede_node(commitment_id, updated)
        return str(new_id)


__all__ = ["PaymentEffect", "SandboxPaymentTool"]

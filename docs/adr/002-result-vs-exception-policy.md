# ADR-002: Result-vs-exception policy

**Status:** accepted
**Phase:** 0
**Date:** 2026-08-22

## Context

PHASES.md §2.2 requires: "Result types for expected failure paths (low
confidence, escalation needed). Exceptions are for the genuinely
unexpected." `contracts/` needs one policy applied consistently, or E1-E4
will each improvise their own convention and produce inconsistent error
handling across the codebase.

## Decision

Two mechanisms, used in two distinct layers, never mixed within a layer:

1. **Typed exceptions (`contracts.errors`)** for reasoning-layer and
   repository-layer conditions that must interrupt the current call and be
   handled by a specific, known caller up the stack — `LowConfidenceError`,
   `EscalationRequired`, `ConstraintViolation`, `AmbiguousEntity`,
   `ApprovalRequired`, `OutOfBounds`, `ProvenanceMissing`,
   `IdempotencyConflict`, `RegistryGap`. These are raised by agents
   (E2) and repositories (E1), and caught at defined orchestration
   boundaries (`backend/app/agents/orchestration/`, `backend/app/
   arbitration/`) that know how to translate them into escalation state,
   an `ApprovalRequest`, or a rejected write. They are *expected* in the
   sense that the system design accounts for them, but they still use
   Python's exception mechanism because the alternative — every reasoning
   function returning a Result that every caller must explicitly check —
   would bury the one condition PHASES.md actually calls out as
   structural (provenance rejection) under boilerplate that invites a
   caller to skip the check.
2. **`contracts.actions.ActionResult[T]`** specifically for the return
   value of `Action.execute()` (the tool layer, E3). Tools return
   `ActionResult.success(...)` or `ActionResult.failure(...)` rather than
   raising, because callers at this layer (the Approval Gate, the
   Fallback Coordinator) need to branch synchronously on success/failure
   as a normal, frequent outcome — a failed outbound call or a failed
   payment attempt is not exceptional, it is the expected shape of roughly
   half of all real-world tool invocations, and safety invariant #7 ("a
   failed tool call never produces a fabricated success") is most directly
   testable against an explicit return value.

`contracts.errors.ToolFailure` still exists as an exception class for the
narrower case of a tool implementation itself throwing before it can even
construct an `ActionResult` (e.g. a network client raising) — the tool's
own wrapper is responsible for catching that and converting it to
`ActionResult.failure(...)`, never letting it propagate un-translated.

## Alternatives considered

- **Result types everywhere, no exceptions.** Rejected: would force every
  repository read and every agent call to explicitly unwrap a Result,
  adding noise to the ~50-line-function budget without a corresponding
  safety benefit for conditions that already have one obvious handler up
  the stack.
- **Exceptions everywhere, no Result type.** Rejected: makes it easy for a
  tool failure to be accidentally swallowed by a broad `except` somewhere
  in a long agent pipeline, which is exactly what invariant #7 exists to
  prevent — an explicit return value is harder to silently discard than a
  caught-and-ignored exception.

## Consequences

- Every tool implementation (E3) must be tested for both branches of
  `ActionResult` — a tool that can only ever return `.success(...)` in its
  test suite has not been tested for the failure path required by every
  gate.
- Every reasoning-layer typed exception must be caught somewhere concrete
  — an uncaught `EscalationRequired` reaching the top of the ADK
  orchestration stack is a defect, not acceptable "the framework will
  handle it" behaviour.

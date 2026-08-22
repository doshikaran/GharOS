"""GharOS — frozen typed error taxonomy.

Owned exclusively by the CTO. No bare `except:` and no swallowed exceptions
anywhere in the codebase (gharos-standards skill, rule 7) — every expected
failure path raises or returns one of these, never a generic Exception.

Per PHASES.md §2.2, exceptions are for the genuinely unexpected; expected
failure paths (low confidence, escalation needed) should generally be
modeled as Result types (see `actions.py:ActionResult`) rather than raised.
These exception classes exist for the cases each subsystem's spec explicitly
calls a *failure mode* that must interrupt a call stack (e.g. a repository
write missing provenance must not be catchable-and-ignored).
"""

from __future__ import annotations


class GharOSError(Exception):
    """Base class for every typed GharOS error. Never raise a bare Exception."""


class LowConfidenceError(GharOSError):
    """A derived node, edge, or proposed action fell below its action tier's
    confidence floor. The caller must downgrade tier, escalate, or discard —
    never silently proceed (spec §19.2, safety invariant #4)."""

    def __init__(self, *, subject: str, confidence: float, floor: float) -> None:
        self.subject = subject
        self.confidence = confidence
        self.floor = floor
        super().__init__(f"{subject}: confidence {confidence:.2f} below floor {floor:.2f}")


class EscalationRequired(GharOSError):
    """Raised when a reasoning step cannot resolve ambiguity itself and must
    hand off to a human (e.g. hard-constraint ambiguity — spec §13, A13's
    forbidden list: 'always escalate, never resolve optimistically')."""

    def __init__(self, *, reason: str, context: dict[str, str] | None = None) -> None:
        self.reason = reason
        self.context = context or {}
        super().__init__(reason)


class ConstraintViolation(GharOSError):
    """A candidate obligation or action violates a HARD constraint. Carries
    enough context for the Conflict Radar / Constraint Checker's caller to
    render the violation without re-deriving it."""

    def __init__(self, *, constraint_id: str, obligation_id: str, detail: str) -> None:
        self.constraint_id = constraint_id
        self.obligation_id = obligation_id
        self.detail = detail
        super().__init__(f"constraint {constraint_id} violated by {obligation_id}: {detail}")


class AmbiguousEntity(GharOSError):
    """Entity resolution could not confidently map a mention to one graph
    node. Spec §15.2 A5: never guess on hard-constraint-bearing entities —
    this error is how that rule is enforced structurally."""

    def __init__(self, *, mention: str, candidates: tuple[str, ...], hard_constraint_bearing: bool) -> None:
        self.mention = mention
        self.candidates = candidates
        self.hard_constraint_bearing = hard_constraint_bearing
        super().__init__(f"ambiguous entity '{mention}': candidates={candidates}")


class ToolFailure(GharOSError):
    """A tool invocation failed. This is the *only* acceptable way for a
    tool to report failure — a failed tool call must never produce a
    fabricated success (safety invariant #7). Callers must not catch this
    and re-narrate it as a success."""

    def __init__(self, *, tool_name: str, reason: str, retryable: bool) -> None:
        self.tool_name = tool_name
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"tool '{tool_name}' failed: {reason} (retryable={retryable})")


class ApprovalRequired(GharOSError):
    """An action at R2 or above was attempted without a prior APPROVED
    ApprovalRequest. This should be structurally unreachable for a
    correctly-wired Approval Gate (spec §18); raising it is a defect, not
    normal control flow, and a test must exist proving it cannot happen for
    each T4/T5/T6 tool (PHASES.md Gate 5)."""

    def __init__(self, *, action_type: str, risk_tier: str) -> None:
        self.action_type = action_type
        self.risk_tier = risk_tier
        super().__init__(f"action '{action_type}' at tier {risk_tier} attempted without approval")


class OutOfBounds(GharOSError):
    """A voice call (or other bounded action) attempted to commit to
    something outside its pre-authorised bounds (spec §13.3: 'the voice
    agent may never agree to anything outside its pre-authorised bounds').
    The caller's response must be graceful decline / callback, never a
    guess."""

    def __init__(self, *, bound_name: str, requested: str, authorised: str) -> None:
        self.bound_name = bound_name
        self.requested = requested
        self.authorised = authorised
        super().__init__(f"out of bounds on '{bound_name}': requested={requested}, authorised={authorised}")


class ProvenanceMissing(GharOSError):
    """Raised by the graph repository write layer when a node or edge is
    missing `source_ref`, `derivation`, `confidence`, or `deriving_agent`.
    This is E1's single most important defence (PHASES.md Phase 1) and
    directly implements safety invariant #3. It must be structurally
    impossible to catch-and-ignore this in a write path — proven by a
    hypothesis fuzz test at Gate 1."""

    def __init__(self, *, missing_fields: tuple[str, ...]) -> None:
        self.missing_fields = missing_fields
        super().__init__(f"provenance write rejected: missing {missing_fields}")


class IdempotencyConflict(GharOSError):
    """A T3+ tool invocation was replayed with the same idempotency key but
    produced (or would produce) a different effect than the original. A
    same-key replay with an *identical* effect is not an error — it is a
    no-op returning the original result (spec §19.1)."""

    def __init__(self, *, idempotency_key: str, original_result_ref: str) -> None:
        self.idempotency_key = idempotency_key
        self.original_result_ref = original_result_ref
        super().__init__(f"idempotency key '{idempotency_key}' conflict")


class RegistryGap(GharOSError):
    """Raised (and logged, not just raised) when the Intake Router or a
    document extractor encounters a document type not present in the
    Document-Type Registry. Per spec §5.4.3 rule 4, this is how the
    registry grows — it always routes to human triage, never a silent
    discard."""

    def __init__(self, *, detection_summary: str) -> None:
        self.detection_summary = detection_summary
        super().__init__(f"registry gap: {detection_summary}")

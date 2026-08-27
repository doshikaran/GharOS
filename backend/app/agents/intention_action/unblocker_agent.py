"""A24 — Unblocker / Preparation Agent (spec §9.3 Stage 3, §15.9).

*Responsibility:* given A23's diagnosis, do the real, corresponding
unblocking work per blocker type:

- **information** — fetch the real missing fact from the household graph
  (T0 read). Gate 9: "Information blocker -> fact fetched."
- **decision** — narrow an open decision to a real binary framing (never
  resolve it). Gate 9: "Decision blocker -> narrowed to binary."
- **aversion** — switch to a genuinely different communication modality
  and pre-draft the replacement. Gate 9: "Aversion blocker -> modality
  switched."
- **first-step-ambiguity** — decompose the task into one concrete,
  unambiguous first action.

`window` blockers are A25 Window Scheduling's job, and `dependency`
blockers need their upstream obligation resolved first (not something
*this* obligation's own unblocking work can fix) — this module
deliberately implements no method for either; a caller routes those
blocker types elsewhere.

*Model tier:* Flash for retrieval (`fetch_information` — turning a real
fetched graph fact into a plain-language answer is normalisation, not
judgment); Pro-tier for narrowing/drafting (`narrow_decision`,
`switch_modality`, `decompose_first_step` — spec §15.9 A24: "Flash for
retrieval, Pro-tier for narrowing/drafting").

*Tools:* **T0 read only** (`app.tools.graph_read_tool.GraphReadTool`, via
a `ToolRegistry` constructed with `allowed_tiers=frozenset({PermissionTier.
T0_READ})`) — attempting to register anything else against it fails
exactly like `StaffPayrollAgent`'s T3-only registry does for a T6 tool.

There is deliberately no literal `PermissionTier.T2_DRAFT` `Tool` object
here: no such concrete tool exists in `backend/app/tools/` yet (E3's
directory, not built this phase), and this codebase's own established
precedent for "Tools: draft only" (`app.agents.ledger.
recovery_drafting_agent`, A30, spec's roster line reads identically) is a
*zero-tool* Pro-tier call producing a real, typed draft-text field — never
a formal tool object. `narrow_decision`, `switch_modality`, and
`decompose_first_step` follow that exact precedent: real Pro-tier
reasoning, a real typed output, and — the part that actually matters for
safety — **no import of `contracts.tools.ApprovalGatedTool` or anything
under `app.arbitration` anywhere in this module**, so there is no path
from here to a send/dispatch capability regardless of how the drafting
tool question is resolved. See this phase's final report for this
judgment call spelled out explicitly.

*Forbidden:* **send without approval.** No T4 tool, no import of
anything gated — checked structurally in
`backend/tests/test_unblocker_agent.py`.
"""

from __future__ import annotations

import uuid

from contracts.actions import ActionResult
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import AgentId
from contracts.repositories import GraphReader
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...tools.graph_read_tool import GraphReadTool
from ...tools.registry import ToolRegistry
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_int, require_str
from .types import (
    AversionModality,
    DecisionNarrowingRequest,
    DecisionNarrowingResult,
    FirstStepDecompositionRequest,
    FirstStepDecompositionResult,
    InformationFetchRequest,
    InformationFetchResult,
    ModalitySwitchRequest,
    ModalitySwitchResult,
)

AGENT_ID = AgentId("A24")

_VALID_MODALITIES: frozenset[str] = frozenset({"call", "message", "in_person", "email", "app_form"})


def _cast_modality(value: str) -> AversionModality:
    """Narrows a validated (member-of-`_VALID_MODALITIES`) string to the
    `AversionModality` literal — mirrors `app.agents.ledger.
    leakage_detection_agent.cast_verdict`'s same role: the one runtime
    check in `switch_modality` above is also what satisfies the static
    type checker, rather than a bare `# type: ignore` at the construction
    site."""
    if value == "call":
        return "call"
    if value == "message":
        return "message"
    if value == "in_person":
        return "in_person"
    if value == "email":
        return "email"
    return "app_form"


class UnblockerAgent:
    """A24 Unblocker / Preparation. Dependency-injected on a
    `GeminiClient` plus a `GraphReader`, wrapped immediately into a
    T0-only `ToolRegistry` and never stored directly on `self` (mirrors
    `ValuationExtractionAgent`'s T3-only construction pattern, narrowed
    to T0 here)."""

    def __init__(self, *, gemini_client: GeminiClient, graph_reader: GraphReader) -> None:
        self._gemini_client = gemini_client
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T0_READ})
        )
        self._tool_registry.register(GraphReadTool(graph_reader=graph_reader))

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same adversarial-proof reason
        `ValuationExtractionAgent.tool_registry` is — a T2/T3/T4/T5/T6
        tool registration attempt against this registry must be
        rejected, checkable directly without running the agent."""
        return self._tool_registry

    def fetch_information(self, request: InformationFetchRequest) -> InformationFetchResult:
        """Information blocker unblocking: runs the caller-specified,
        real graph query and (only if it found something) asks Flash to
        phrase the raw result into a plain-language answer to
        `missing_fact_description`.

        Args:
            request: the missing fact description plus the real graph
                query (`GraphQuerySpec`) the caller has already determined
                would answer it.

        Returns:
            `InformationFetchResult(fetched=True, ...)` when the query
            found something; `fetched=False, fact_text=None` (never a
            fabricated fact) when it did not, or when the tool call
            itself failed.
        """
        tool = self._tool_registry.get("graph_reader")
        assert isinstance(tool, GraphReadTool)  # registered by this class's own __init__, always present

        result: ActionResult[object]
        try:
            result = tool.invoke(operation=request.query.operation, **request.query.args)
        except ToolFailure:
            result = ActionResult.failure("graph query failed")

        if not result.ok or result.value is None or (isinstance(result.value, tuple) and not result.value):
            return InformationFetchResult(
                obligation_id=request.obligation_id,
                missing_fact_description=request.missing_fact_description,
                fetched=False,
                fact_text=None,
                confidence=0.0,
                model_tier="flash",
                prompt_version=None,
                invocation_id=uuid.uuid4().hex,
            )

        prompt = load_prompt("A24_INFO")
        rendered = prompt.text.format(
            missing_fact_description=request.missing_fact_description, raw_result=repr(result.value)
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        return InformationFetchResult(
            obligation_id=request.obligation_id,
            missing_fact_description=request.missing_fact_description,
            fetched=True,
            fact_text=require_str(parsed, "fact_text", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="flash",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def narrow_decision(self, request: DecisionNarrowingRequest) -> DecisionNarrowingResult:
        """Decision blocker unblocking: Pro-tier narrowing to a real
        binary framing.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed, or `option_a`/`option_b` were identical.
        """
        known_options_block = (
            "\n".join(f"- {opt}" for opt in request.known_options) or "(none surfaced yet)"
        )
        known_facts_block = "\n".join(f"- {fact}" for fact in request.known_facts) or "(none)"
        prompt = load_prompt("A24_DECISION")
        rendered = prompt.text.format(
            decision_summary=request.decision_summary,
            known_options_block=known_options_block,
            known_facts_block=known_facts_block,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        option_a = require_str(parsed, "option_a", agent_id=AGENT_ID)
        option_b = require_str(parsed, "option_b", agent_id=AGENT_ID)
        if option_a.strip().lower() == option_b.strip().lower():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="option_a and option_b must be distinct", raw_text=call_result.text
            )
        return DecisionNarrowingResult(
            obligation_id=request.obligation_id,
            option_a=option_a,
            option_b=option_b,
            framing_text=require_str(parsed, "framing_text", agent_id=AGENT_ID),
            reasoning=require_str(parsed, "reasoning", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def switch_modality(self, request: ModalitySwitchRequest) -> ModalitySwitchResult:
        """Aversion blocker unblocking: Pro-tier modality switch plus a
        real pre-drafted replacement communication.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed, or echoed back `request.avoided_modality` as
                `to_modality` (a "switch" to the same modality is not a
                switch).
        """
        prompt = load_prompt("A24_AVERSION")
        rendered = prompt.text.format(
            avoided_modality=request.avoided_modality,
            task_summary=request.task_summary,
            counterparty_name=request.counterparty_name,
            known_facts_block="\n".join(f"- {fact}" for fact in request.known_facts) or "(none)",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        to_modality_raw = require_str(parsed, "to_modality", agent_id=AGENT_ID)
        if to_modality_raw not in _VALID_MODALITIES:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"unrecognised to_modality {to_modality_raw!r}",
                raw_text=call_result.text,
            )
        if to_modality_raw == request.avoided_modality:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason="to_modality must differ from avoided_modality — this is not a switch",
                raw_text=call_result.text,
            )
        return ModalitySwitchResult(
            obligation_id=request.obligation_id,
            from_modality=request.avoided_modality,
            to_modality=_cast_modality(to_modality_raw),
            pre_drafted_text=require_str(parsed, "pre_drafted_text", agent_id=AGENT_ID),
            reasoning=require_str(parsed, "reasoning", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def decompose_first_step(self, request: FirstStepDecompositionRequest) -> FirstStepDecompositionResult:
        """First-step-ambiguity blocker unblocking: Pro-tier decomposition
        into one concrete, unambiguous first action."""
        prompt = load_prompt("A24_FIRST_STEP")
        rendered = prompt.text.format(
            task_summary=request.task_summary,
            known_facts_block="\n".join(f"- {fact}" for fact in request.known_facts) or "(none)",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        estimated_minutes_raw = parsed.get("estimated_minutes")
        estimated_minutes = (
            require_int(parsed, "estimated_minutes", agent_id=AGENT_ID)
            if estimated_minutes_raw is not None
            else None
        )
        return FirstStepDecompositionResult(
            obligation_id=request.obligation_id,
            first_action_text=require_str(parsed, "first_action_text", agent_id=AGENT_ID),
            estimated_minutes=estimated_minutes,
            reasoning=require_str(parsed, "reasoning", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )


__all__ = ["AGENT_ID", "UnblockerAgent"]

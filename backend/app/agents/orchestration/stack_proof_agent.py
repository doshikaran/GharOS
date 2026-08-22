"""Phase 2 mandatory-stack-proof ADK agent.

PHASES.md Phase 2 work item ("a trivial ADK agent with one tool, deployed
and invoked, proving the framework works") and Gate 2 requirement 2 ("a
Google ADK agent executing a tool call ... proving the framework works").

This is **not** one of the 69 numbered agents in spec §15's roster — it
exists solely to prove the ADK plumbing (agent receives a request -> agent
decides to call a tool -> tool executes for real -> tool result is
returned to the agent -> agent produces a final response grounded in that
result) works end-to-end against a live Vertex AI Gemini model, and to
establish the construction pattern every real ADK-backed roster agent from
Phase 3 onward follows:

1. Resolve a model via `reasoning.model_router.ModelRouter.route()` —
   the single Pro-tier-allowlist enforcement point.
2. Bind the resolved model name into an ADK `Gemini` model via
   `agents.base.gemini_model_for`.
3. Wrap it in a `google.adk.agents.Agent` with typed
   `google.adk.tools.FunctionTool`s.
4. Drive one turn through a `google.adk.runners.Runner` and inspect the
   yielded `Event`s for genuine `get_function_calls()` /
   `get_function_responses()` — never just trust the final text, which an
   LLM could produce without actually invoking anything.

The instruction string below is inline rather than sourced from
`backend/app/prompts/` (ADR-003's versioned-prompt convention) because
this is diagnostic scaffolding, not a roster agent with a citable output —
every real roster agent built on this pattern from Phase 3 onward sources
its instruction from `backend/app/prompts/<agent_id>_<name>/` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from ...reasoning.model_router import ModelRouter
from ..base import gemini_model_for
from ..errors import AgentRunIncomplete

logger = structlog.get_logger(__name__)

STACK_PROOF_AGENT_ID = AgentId("DEBUG-STACK-PROOF")
"""Deliberately **not** a roster agent id (spec §15 defines A0-A69 only,
`model_router.PRO_TIER_ALLOWLIST` only ever contains roster ids) — a
distinct, unmistakably-non-roster identity for this diagnostic demo so its
invocation trace can never be confused with a real agent's. Only ever
requests `ModelTier.FLASH`, so it never needs Pro-tier allowlist
membership."""

_APP_NAME = "gharos-stack-proof"
_USER_ID = "gharos-debug"
_INSTRUCTION = (
    "You are a diagnostic agent that proves tool-calling works end to end. "
    "When asked for the current time, you MUST call the get_current_utc_time "
    "tool and report exactly the value it returns. Never guess, estimate, or "
    "fabricate a time yourself — always call the tool first."
)
_USER_QUESTION = "What is the current UTC time?"


def get_current_utc_time() -> dict[str, str]:
    """ADK tool: returns the current UTC time as an ISO-8601 string.

    Deliberately trivial and self-contained (reads only the system clock,
    no network or credentials) — Gate 2 requires proof that a tool call
    genuinely executes, not a demonstration of a complex integration.
    """
    return {"utc_time": datetime.now(UTC).isoformat()}


@dataclass(frozen=True, slots=True)
class StackProofResult:
    """Proof artifact for Gate 2 requirement 2. Constructed only when the
    ADK run genuinely invoked `get_current_utc_time` and produced a final
    response — see `run_stack_proof_demo`'s `Raises` section."""

    response_text: str
    tool_name: str
    tool_result: dict[str, str]
    model_name: str
    produced_at: datetime


async def run_stack_proof_demo(*, router: ModelRouter, project_id: str, location: str) -> StackProofResult:
    """Runs one real ADK turn proving agent -> tool call -> tool result ->
    agent response works end to end.

    Args:
        router: resolves the Flash-tier model this demo agent uses.
        project_id: GCP project id for the underlying Vertex AI client.
        location: Vertex AI location for the underlying Vertex AI client.

    Returns:
        A `StackProofResult` confirming the tool was actually invoked
        (`tool_name`, `tool_result` come from `Event.get_function_calls()`
        / `get_function_responses()`, not from parsing the model's prose).

    Raises:
        ProTierNotAllowlisted: never expected (this demo only requests
            `ModelTier.FLASH`) — propagates unchanged if it somehow occurs.
        InvalidRoutingTier: never expected, same reasoning.
        GeminiCallFailed: the underlying Vertex AI call itself failed.
        AgentRunIncomplete: the ADK run completed without invoking
            `get_current_utc_time`, or without producing a final text
            response — a genuine plumbing failure, never reinterpreted as
            success (safety invariant #7).
    """
    routed = router.route(agent_id=STACK_PROOF_AGENT_ID, requested_tier=ModelTier.FLASH)
    model = gemini_model_for(routed, project_id=project_id, location=location)

    agent = Agent(
        name="stack_proof_agent",
        model=model,
        instruction=_INSTRUCTION,
        tools=[FunctionTool(get_current_utc_time)],
    )

    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
    runner = Runner(app_name=_APP_NAME, agent=agent, session_service=session_service)

    tool_name: str | None = None
    tool_result: dict[str, str] | None = None
    response_text: str | None = None

    async for event in runner.run_async(
        user_id=_USER_ID,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=_USER_QUESTION)]),
    ):
        for call in event.get_function_calls():
            if call.name is not None:
                tool_name = call.name
        for response in event.get_function_responses():
            if response.response is not None:
                tool_result = {str(key): str(value) for key, value in response.response.items()}
        if event.is_final_response() and event.content and event.content.parts:
            first_part_text = event.content.parts[0].text
            if first_part_text is not None:
                response_text = first_part_text

    if tool_name is None or tool_result is None:
        logger.warning(
            "agents.orchestration.stack_proof.no_tool_call",
            model_name=routed.model_name,
        )
        raise AgentRunIncomplete(
            agent_id=STACK_PROOF_AGENT_ID,
            reason="ADK run completed without invoking get_current_utc_time",
        )
    if response_text is None:
        logger.warning(
            "agents.orchestration.stack_proof.no_final_response",
            model_name=routed.model_name,
        )
        raise AgentRunIncomplete(
            agent_id=STACK_PROOF_AGENT_ID,
            reason="ADK run completed without a final text response",
        )

    logger.info(
        "agents.orchestration.stack_proof.succeeded",
        model_name=routed.model_name,
        tool_name=tool_name,
    )
    return StackProofResult(
        response_text=response_text,
        tool_name=tool_name,
        tool_result=tool_result,
        model_name=routed.model_name,
        produced_at=datetime.now(UTC),
    )

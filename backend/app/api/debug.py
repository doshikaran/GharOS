"""GharOS — Phase 2 mandatory-stack-proof diagnostic endpoints (E2 —
Agents & Reasoning).

PHASES.md Gate 2 requires two demonstrable proofs this module exposes as
real, hittable HTTP endpoints rather than one-off scripts, so the same
proof works locally today and against the deployed `gharos-api` Cloud Run
service once E3's deployment is wired up (PHASES.md Phase 2 E3 work
items):

- `GET /debug/gemini-ping` — Gate 2 requirement 1: "Gemini 3.5+ via
  Vertex AI responding". Makes one real Flash-tier call through
  `reasoning.model_router.ModelRouter` + `reasoning.gemini_client.GeminiClient`.
- `POST /debug/adk-demo` — Gate 2 requirement 2: "a Google ADK agent
  executing a tool call ... proving the framework works". Runs
  `agents.orchestration.stack_proof_agent.run_stack_proof_demo` and
  returns proof (from the ADK run's own event stream, not the model's
  prose) that a tool was genuinely invoked.

Neither endpoint is itself a T-tiered action tool (E3-owned,
`backend/app/tools/`) — both only read a live model response and return
it; nothing here writes to the graph, sends a message, or moves money, so
neither needs the Approval Gate.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..agents.errors import AgentRunIncomplete
from ..agents.orchestration.stack_proof_agent import run_stack_proof_demo
from ..reasoning.errors import GeminiCallFailed
from ..reasoning.gemini_client import GeminiClient
from ..reasoning.model_router import ModelRouter
from ..settings import Settings, get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

GEMINI_PING_AGENT_ID = AgentId("DEBUG-GEMINI-PING")
"""Same non-roster-id convention as
`agents.orchestration.stack_proof_agent.STACK_PROOF_AGENT_ID` — a
diagnostic ping is not a real roster agent invocation and must never be
recorded or mistaken for one in an invocation trace. Only ever requests
`ModelTier.FLASH`, so it never needs Pro-tier allowlist membership."""

_PING_PROMPT = "Reply with exactly the single word: pong"


def get_model_router(settings: Annotated[Settings, Depends(get_settings)]) -> ModelRouter:
    """Builds a `ModelRouter` bound to this process's configured GCP
    project/location/model set.

    Dependency-injected (a FastAPI `Depends` provider, not a module-level
    singleton) so tests can override it via `app.dependency_overrides`
    with a fake client factory instead of making a real network call —
    gharos-standards: no module-level singleton holding a live client.
    """
    return ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )


def get_gemini_client(model_router: Annotated[ModelRouter, Depends(get_model_router)]) -> GeminiClient:
    """Builds a `GeminiClient` over the injected `ModelRouter`."""
    return GeminiClient(router=model_router)


class GeminiPingResponse(BaseModel):
    """Response body for `GET /debug/gemini-ping`."""

    response_text: str
    model_tier: str
    model_name: str


@router.get("/gemini-ping", response_model=GeminiPingResponse)
def gemini_ping(gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)]) -> GeminiPingResponse:
    """Makes one real Flash-tier Gemini call through `ModelRouter` +
    `GeminiClient` and returns the response text plus which model tier
    was used — Gate 2 requirement 1.

    Raises:
        HTTPException: 502 if the live Vertex AI call failed or returned
            no text — never silently reinterpreted as a fabricated "pong"
            (safety invariant #7).
    """
    try:
        result = gemini_client.generate_text(
            agent_id=GEMINI_PING_AGENT_ID, tier=ModelTier.FLASH, prompt=_PING_PROMPT
        )
    except GeminiCallFailed as exc:
        logger.warning("api.debug.gemini_ping.failed", reason=str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    logger.info("api.debug.gemini_ping.succeeded", model_name=result.model_name)
    return GeminiPingResponse(
        response_text=result.text,
        model_tier=result.tier.value,
        model_name=result.model_name,
    )


class AdkDemoResponse(BaseModel):
    """Response body for `POST /debug/adk-demo`."""

    response_text: str
    tool_invoked: str
    tool_result: dict[str, str]
    model_name: str


@router.post("/adk-demo", response_model=AdkDemoResponse)
async def adk_demo(
    settings: Annotated[Settings, Depends(get_settings)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> AdkDemoResponse:
    """Runs the Phase 2 stack-proof ADK agent for real and returns proof
    that its tool was genuinely invoked — Gate 2 requirement 2.

    `tool_invoked` / `tool_result` come from the ADK run's own
    `Event.get_function_calls()` / `get_function_responses()`
    (`stack_proof_agent.run_stack_proof_demo`'s contract) — confirmation
    the tool actually executed, not that the model merely said it would.

    Raises:
        HTTPException: 502 if the ADK run did not genuinely invoke its
            tool, produced no final response, or the underlying Vertex AI
            call failed — never reinterpreted as success.
    """
    try:
        result = await run_stack_proof_demo(
            router=model_router,
            project_id=settings.gcp_project_id,
            location=settings.vertex_ai_location,
        )
    except (AgentRunIncomplete, GeminiCallFailed) as exc:
        logger.warning("api.debug.adk_demo.failed", reason=str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    logger.info("api.debug.adk_demo.succeeded", tool_invoked=result.tool_name)
    return AdkDemoResponse(
        response_text=result.response_text,
        tool_invoked=result.tool_name,
        tool_result=result.tool_result,
        model_name=result.model_name,
    )

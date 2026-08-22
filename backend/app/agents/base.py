"""Shared ADK agent-construction pattern for `backend/app/agents/`.

Every ADK-backed agent — starting with the Phase 2 stack-proof agent
(`agents.orchestration.stack_proof_agent`), and every one of the 69
roster agents from Phase 3 onward that is built as a `google.adk.agents.Agent`
rather than a plain `reasoning.gemini_client.GeminiClient` call — resolves
its model name and Pro-tier eligibility through
`reasoning.model_router.ModelRouter` first, never a raw model string, then
binds that resolved name into an ADK `google.adk.models.Gemini` instance
via `gemini_model_for` below. This keeps `ModelRouter`'s Pro-tier
allowlist as the single enforcement point for tier routing regardless of
whether an agent calls Gemini directly (`GeminiClient`) or through the ADK
framework (`Agent` + `Runner`).
"""

from __future__ import annotations

from google.adk.models.google_llm import Gemini

from ..reasoning.model_router import RoutedModel


def gemini_model_for(routed: RoutedModel, *, project_id: str, location: str) -> Gemini:
    """Builds an ADK `Gemini` model bound to a `ModelRouter`-resolved
    model name, configured for Vertex AI.

    Args:
        routed: the `RoutedModel` returned by `ModelRouter.route()` —
            supplies the allowlist-checked model name for this agent's
            requested tier.
        project_id: GCP project id (`app.settings.Settings.gcp_project_id`).
        location: Vertex AI location (`app.settings.Settings.vertex_ai_location`).

    Returns:
        A `Gemini` model instance that `google.adk.agents.Agent` /
        `google.adk.runners.Runner` can drive. ADK constructs its own
        internal `google.genai.Client` from `client_kwargs` the first
        time the model is used — this deliberately does not reuse
        `routed.client` (the `genai.Client` `ModelRouter` already built
        for direct `GeminiClient` calls), since ADK's `Gemini` model owns
        its own client lifecycle and only accepts client configuration,
        not a pre-built client instance.
    """
    return Gemini(
        model=routed.model_name,
        client_kwargs={"vertexai": True, "project": project_id, "location": location},
    )

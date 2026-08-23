"""GharOS Phase 3 intake-layer agents (spec §15.2, A2-A6) and the
fourteen Document-Type Registry `ExtractionStrategy` implementations
(`backend/app/agents/intake/strategies/`).

Every agent here is E2-owned (`backend/app/agents/`) and follows the same
construction pattern: a plain, dependency-injected class holding a
`reasoning.gemini_client.GeminiClient` (never a raw `google.genai.Client`),
reading its instruction text through `app.prompts.loader.load_prompt`, and
returning a `contracts.agents.AgentOutput`-shaped result alongside its own
typed domain payload.
"""

from __future__ import annotations

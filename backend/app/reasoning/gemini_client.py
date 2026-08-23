"""A real, reusable Vertex AI Gemini call wrapper built on `model_router.py`.

PHASES.md Phase 2 work item ("a live Gemini 3.5+ call through Vertex AI")
and Gate 2 requirement 1 ("Gemini 3.5+ via Vertex AI responding..."). This
module is the single place a plain text-in/text-out Gemini call is made —
every caller (starting with `app.api.debug`'s `/debug/gemini-ping`, and
every one of the 69 roster agents from Phase 3 onward that needs a simple
generation call rather than the full ADK agent/tool loop) goes through
`GeminiClient.generate_text()` rather than touching `google.genai` or
`ModelRouter.route()` directly, so tier routing, the Pro-tier allowlist,
and failure handling are enforced in exactly one place.

Agents that need tool-calling, multi-turn state, or callbacks use the ADK
pattern in `backend/app/agents/base.py` instead (`gemini_model_for`,
consumed by `backend/app/agents/orchestration/stack_proof_agent.py`) — that
path also resolves its model through `ModelRouter.route()`, so both entry
points share the same allowlist enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google.genai import errors as genai_errors
from google.genai import types

from .errors import GeminiCallFailed
from .model_router import ModelRouter

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MediaPart:
    """One inline binary part (an image or PDF page) for a multimodal
    Gemini call — `GeminiClient.generate_multimodal`'s input shape for the
    real image/PDF bytes A3 (Document Extraction) and A3b (Line-Item
    Extraction) send Gemini, never a description of the bytes (spec §15.2
    A3: extraction reads the actual document)."""

    data: bytes
    mime_type: str


@dataclass(frozen=True, slots=True)
class GeminiCallResult:
    """A completed, successful Gemini call — never constructed for a
    failed or empty response (see `GeminiClient.generate_text`'s
    `Raises` section); a failed call always raises `GeminiCallFailed`
    instead (safety invariant #7 — no fabricated success)."""

    agent_id: AgentId
    tier: ModelTier
    model_name: str
    text: str
    produced_at: datetime


class GeminiClient:
    """Thin wrapper around a `ModelRouter`-resolved `google.genai.Client`
    for single-turn, text-in/text-out Gemini calls.

    Dependency-injected per gharos-standards: holds a `ModelRouter`
    instance, not a raw client — no module-level singleton, and every
    call re-resolves through the router so the allowlist is checked on
    every invocation, not just at construction time.
    """

    def __init__(self, *, router: ModelRouter) -> None:
        """Args:
        router: the `ModelRouter` this client resolves every call
            through. Owns the Pro-tier allowlist check and the model
            name resolution.
        """
        self._router = router

    def generate_text(self, *, agent_id: AgentId, tier: ModelTier, prompt: str) -> GeminiCallResult:
        """Makes one live text-generation call to Vertex AI Gemini.

        Args:
            agent_id: the calling agent's id — checked against
                `model_router.PRO_TIER_ALLOWLIST` when `tier` is
                `ModelTier.PRO`.
            tier: `ModelTier.FLASH` or `ModelTier.PRO`. `ModelTier.DETERMINISTIC`
                is rejected by `ModelRouter.route()` before any call is made.
            prompt: the raw text prompt to send.

        Returns:
            A `GeminiCallResult` carrying the response text and the
            resolved model name/tier actually used.

        Raises:
            ProTierNotAllowlisted: `tier` is `ModelTier.PRO` and
                `agent_id` is not on the allowlist (raised by
                `ModelRouter.route()`, propagates unchanged).
            InvalidRoutingTier: `tier` is `ModelTier.DETERMINISTIC`
                (raised by `ModelRouter.route()`, propagates unchanged).
            GeminiCallFailed: the underlying Vertex AI call raised, or
                returned a response with no text content — a failed or
                empty call is never reinterpreted as an empty success.
        """
        return self._invoke(agent_id=agent_id, tier=tier, contents=prompt, response_mime_type=None)

    def generate_structured(
        self, *, agent_id: AgentId, tier: ModelTier, prompt: str
    ) -> GeminiCallResult:
        """Like `generate_text`, but asks Vertex AI to constrain its
        response to `application/json` — used by every Phase 3 intake
        agent (A2, A4, A5, A6) whose output this codebase parses as JSON
        rather than free text. Prompts using this method must still spell
        out the exact expected JSON shape themselves; `response_mime_type`
        alone only constrains the *envelope*, not the schema within it.

        Raises: same as `generate_text`.
        """
        return self._invoke(
            agent_id=agent_id, tier=tier, contents=prompt, response_mime_type="application/json"
        )

    def generate_multimodal(
        self,
        *,
        agent_id: AgentId,
        tier: ModelTier,
        prompt: str,
        media: tuple[MediaPart, ...] = (),
        response_mime_type: str | None = "application/json",
    ) -> GeminiCallResult:
        """Makes one live multimodal call to Vertex AI Gemini — the entry
        point A3 (Document Extraction) and A3b (Line-Item Extraction) use
        to send real image/PDF bytes alongside a text prompt (spec §15.2:
        "Gemini multimodal — Flash for clean, Pro-tier for degraded/
        handwriting"). `media` is empty for a text-shaped source document
        (an email body, an SMS, a chat export) — those go through
        `generate_structured` instead, since there is nothing to attach.

        Args:
            agent_id: as `generate_text`.
            tier: as `generate_text`.
            prompt: the text instruction/schema description.
            media: zero or more `MediaPart`s (real image/PDF bytes) to
                attach — each becomes one inline `types.Part` alongside
                the prompt text, in a single user turn.
            response_mime_type: forwarded into `types.GenerateContentConfig`
                when set (the default, `"application/json"`, matches every
                current caller's structured-extraction use case); pass
                `None` for a call that wants free text back.

        Returns: same shape as `generate_text`.

        Raises: same as `generate_text`.
        """
        parts: list[types.Part] = [types.Part(text=prompt)]
        for part in media:
            parts.append(types.Part.from_bytes(data=part.data, mime_type=part.mime_type))
        return self._invoke(
            agent_id=agent_id, tier=tier, contents=parts, response_mime_type=response_mime_type
        )

    def _invoke(
        self,
        *,
        agent_id: AgentId,
        tier: ModelTier,
        contents: str | list[types.Part],
        response_mime_type: str | None,
    ) -> GeminiCallResult:
        """Shared call path behind `generate_text`/`generate_structured`/
        `generate_multimodal` — resolves the model once, makes exactly one
        `generate_content` call, and applies the one failure-handling
        policy (safety invariant #7) uniformly regardless of which public
        method the caller used.

        `generate_text` passes `contents` through as the bare prompt
        string it always has, unchanged from this module's original
        (pre-multimodal) behaviour — callers and tests that depend on the
        exact `generate_content(model=..., contents=<str>)` call shape for
        a plain text call are unaffected by this method's existence.

        The `cast(Any, ...)` below is a narrow, justified interop
        boundary: the installed `google-genai` SDK spells
        `generate_content(contents=...)`'s parameter type as an inline
        `Union` (not a named, importable alias) whose `list[...]` members
        are *invariant* under mypy's variance rules (see mypy's own "list
        is invariant" note) — a genuinely-valid `list[types.Part]` does
        not structurally match the SDK's broader `list[Part | ...]`
        member even though every element satisfies it, and there is no
        SDK-exported alias this module can cast to instead that mypy
        accepts. `contents` here is only ever a bare `str` (from
        `generate_text`/`generate_structured`) or a `list[types.Part]`
        this module itself builds (`generate_multimodal`) — both real,
        valid values the SDK accepts at runtime; this repo's
        `reasoning.errors.GeminiCallFailed` handling below still applies
        if that assumption is ever wrong.
        """
        routed = self._router.route(agent_id=agent_id, requested_tier=tier)
        config = (
            types.GenerateContentConfig(response_mime_type=response_mime_type) if response_mime_type else None
        )
        sdk_contents = cast(Any, contents)

        try:
            if config is not None:
                response = routed.client.models.generate_content(
                    model=routed.model_name, contents=sdk_contents, config=config
                )
            else:
                response = routed.client.models.generate_content(
                    model=routed.model_name, contents=sdk_contents
                )
        except genai_errors.APIError as exc:
            logger.warning(
                "reasoning.gemini_client.call_failed",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
                reason=str(exc),
            )
            raise GeminiCallFailed(agent_id=agent_id, model_name=routed.model_name, reason=str(exc)) from exc

        text = response.text
        if not text:
            logger.warning(
                "reasoning.gemini_client.empty_response",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
            )
            raise GeminiCallFailed(
                agent_id=agent_id,
                model_name=routed.model_name,
                reason="Vertex AI returned no text content (empty or non-text response)",
            )

        logger.info(
            "reasoning.gemini_client.call_succeeded",
            agent_id=agent_id,
            model_name=routed.model_name,
            tier=tier.value,
        )
        return GeminiCallResult(
            agent_id=agent_id,
            tier=tier,
            model_name=routed.model_name,
            text=text,
            produced_at=datetime.now(UTC),
        )

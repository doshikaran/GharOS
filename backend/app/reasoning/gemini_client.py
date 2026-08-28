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

from collections.abc import Sequence
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


@dataclass(frozen=True, slots=True)
class GroundedCitation:
    """One real external source Vertex AI's Google Search grounding tool
    actually cited for a `generate_grounded_text` call (ADR-017, Phase 11
    Household Simulator A36 Grounding/Research). Parsed from the real
    SDK response shape (`google.genai.types.GroundingChunk.web`) —
    confirmed against a real live call (see
    `test_gemini_client.py::test_real_grounded_call_against_live_search`),
    never invented when grounding did not trigger for a prompt.

    `retrieved_at` is `datetime.now(UTC)` at call time — real, honest
    freshness of *this lookup*, regardless of how old the underlying
    indexed page actually is. A36 states both facts separately and never
    conflates "we looked this up just now" with "this information is
    current" (ADR-017 decision 2)."""

    title: str
    uri: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class GroundedGeminiCallResult:
    """A completed, successful Google-Search-grounded Gemini call. Like
    `GeminiCallResult`, never constructed for a failed or empty response.

    `citations` is empty exactly when Google Search grounding did not
    trigger for this prompt — a real, expected outcome (grounding is not
    guaranteed for every prompt), never backfilled with a fabricated
    citation (ADR-017: "honest fallback, never fabricated")."""

    agent_id: AgentId
    tier: ModelTier
    model_name: str
    text: str
    citations: tuple[GroundedCitation, ...]
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
        self, *, agent_id: AgentId, tier: ModelTier, prompt: str, thinking_budget: int | None = None
    ) -> GeminiCallResult:
        """Like `generate_text`, but asks Vertex AI to constrain its
        response to `application/json` — used by every Phase 3 intake
        agent (A2, A4, A5, A6) whose output this codebase parses as JSON
        rather than free text. Prompts using this method must still spell
        out the exact expected JSON shape themselves; `response_mime_type`
        alone only constrains the *envelope*, not the schema within it.

        Args:
            agent_id: as `generate_text`.
            tier: as `generate_text`.
            prompt: as `generate_text`.
            thinking_budget: opt-in elevated-thinking token budget
                (PHASES.md §2.1 rule 4: "elevated thinking budgets are
                opt-in per agent, never global") — `None` (the default)
                requests no explicit thinking configuration at all, byte-
                for-byte identical to this method's pre-existing behaviour
                for every caller that does not pass it. A caller that does
                pass a value (the Implication Agent, A12, is the first —
                see `agents.consequence.implication_agent`) gets
                `types.ThinkingConfig(thinking_budget=thinking_budget)`
                attached to the call's `GenerateContentConfig`. This
                module owns no policy about *which* agents should request
                elevated thinking or what budget is "elevated" — that is
                each calling agent's own, individually-justified constant,
                never a value this shared client defaults or infers.

        Raises: same as `generate_text`.
        """
        return self._invoke(
            agent_id=agent_id,
            tier=tier,
            contents=prompt,
            response_mime_type="application/json",
            thinking_budget=thinking_budget,
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

    def generate_grounded_text(
        self, *, agent_id: AgentId, tier: ModelTier, prompt: str
    ) -> GroundedGeminiCallResult:
        """Makes one live, Google-Search-grounded text-generation call to
        Vertex AI Gemini (ADR-017, Phase 11 A36 Grounding/Research) —
        attaches `types.Tool(google_search=types.GoogleSearch())` to the
        call's `GenerateContentConfig`, letting the model issue real web
        searches and ground its answer in real, citable results.

        **`response_mime_type` is never set on this call.** Confirmed
        directly against a real live Vertex AI call (not assumed from
        memory, per this project's own live-proof discipline — Phase 2's
        stack proof, ADR-010's live Pro-tier call): attaching
        `response_mime_type="application/json"` alongside the Search
        tool raises a real `400 INVALID_ARGUMENT` — "Unable to submit
        request because controlled generation is not supported with
        Search tool." Tool-use and strict JSON mode are genuinely
        mutually exclusive on the current `google-genai`/Gemini API; a
        grounded call's response is always free text, parsed by whatever
        this method's caller does with `GroundedGeminiCallResult.text`
        (A36 keeps its own output — `GroundingResult` — to a neutral
        prose summary rather than demanding JSON back from this call).

        Args:
            agent_id: the calling agent's id — checked against
                `model_router.PRO_TIER_ALLOWLIST` when `tier` is
                `ModelTier.PRO`, exactly as `generate_text`.
            tier: `ModelTier.FLASH` or `ModelTier.PRO`.
            prompt: the raw text prompt to send — should ask a genuinely
                researchable, real-world question; grounding does not
                trigger for every prompt (see `citations`' own honesty
                contract below).

        Returns:
            A `GroundedGeminiCallResult`. `citations` is empty when
            Google Search grounding did not trigger for this prompt (a
            real, expected outcome) — never fabricated. Every non-empty
            `citations` entry is parsed from the real
            `response.candidates[0].grounding_metadata.grounding_chunks`
            list (confirmed shape, not guessed): each chunk's `web.uri`
            and `web.title` (falling back to `web.domain`, then the URI
            itself, if `title` is unset — the real SDK response has
            returned the bare domain as `title` for some queries, never
            observed unset entirely, but this module does not assume
            either field is always populated).

        Raises:
            ProTierNotAllowlisted: `tier` is `ModelTier.PRO` and
                `agent_id` is not on the allowlist (raised by
                `ModelRouter.route()`, propagates unchanged).
            InvalidRoutingTier: `tier` is `ModelTier.DETERMINISTIC`.
            GeminiCallFailed: the underlying Vertex AI call raised, or
                returned a response with no text content.
        """
        routed = self._router.route(agent_id=agent_id, requested_tier=tier)
        config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])

        try:
            response = routed.client.models.generate_content(
                model=routed.model_name, contents=prompt, config=config
            )
        except genai_errors.APIError as exc:
            logger.warning(
                "reasoning.gemini_client.grounded_call_failed",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
                reason=str(exc),
            )
            raise GeminiCallFailed(agent_id=agent_id, model_name=routed.model_name, reason=str(exc)) from exc

        text = response.text
        if not text:
            logger.warning(
                "reasoning.gemini_client.grounded_empty_response",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
            )
            raise GeminiCallFailed(
                agent_id=agent_id,
                model_name=routed.model_name,
                reason="Vertex AI returned no text content (empty or non-text response)",
            )

        citations = _extract_grounding_citations(response.candidates)
        logger.info(
            "reasoning.gemini_client.grounded_call_succeeded",
            agent_id=agent_id,
            model_name=routed.model_name,
            tier=tier.value,
            citation_count=len(citations),
        )
        return GroundedGeminiCallResult(
            agent_id=agent_id,
            tier=tier,
            model_name=routed.model_name,
            text=text,
            citations=citations,
            produced_at=datetime.now(UTC),
        )

    def _invoke(
        self,
        *,
        agent_id: AgentId,
        tier: ModelTier,
        contents: str | list[types.Part],
        response_mime_type: str | None,
        thinking_budget: int | None = None,
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
        config_kwargs: dict[str, Any] = {}
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        if thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
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


def _extract_grounding_citations(
    candidates: Sequence[types.Candidate] | None,
) -> tuple[GroundedCitation, ...]:
    """Parses `response.candidates[0].grounding_metadata.grounding_chunks`
    into `GroundedCitation`s — the real SDK shape, confirmed against a
    real live Vertex AI Google Search grounding call (not assumed from
    memory): `types.Candidate.grounding_metadata: types.GroundingMetadata
    | None`, `.grounding_chunks: list[types.GroundingChunk] | None`, each
    chunk's `.web: types.GroundingChunkWeb | None` carrying `.uri`,
    `.title`, and `.domain`.

    A module-level function (not a method) — pure, and independently unit-
    testable against a fake `Candidate`/`GroundingMetadata` object without
    constructing a whole fake SDK client.

    Returns:
        Empty tuple whenever `candidates` is falsy, the first candidate
        has no `grounding_metadata`, or `grounding_metadata.grounding_chunks`
        is empty — Google Search grounding genuinely does not trigger for
        every prompt, and this is never backfilled with an invented
        citation (ADR-017). Otherwise one `GroundedCitation` per chunk
        that has a real `web.uri` (a chunk with no `web`, or a `web` with
        no `uri`, contributes nothing — never a citation with a blank or
        guessed URI).
    """
    if not candidates:
        return ()
    grounding_metadata = candidates[0].grounding_metadata
    if grounding_metadata is None:
        return ()
    chunks = grounding_metadata.grounding_chunks
    if not chunks:
        return ()

    retrieved_at = datetime.now(UTC)
    citations: list[GroundedCitation] = []
    for chunk in chunks:
        web = chunk.web
        if web is None or not web.uri:
            continue
        title = web.title or web.domain or web.uri
        citations.append(GroundedCitation(title=title, uri=web.uri, retrieved_at=retrieved_at))
    return tuple(citations)

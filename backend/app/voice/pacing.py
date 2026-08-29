"""Deterministic pacing policy for A69 Voice Response Agent (spec §15.11
A69: "pacing adapted to the listener").

Plain code, not a model call — this codebase's established discipline
(`app.agents.voice.formatting.format_inr`, `app.solvers.salary_calculator`)
is that a policy this safety-adjacent (a household elder or a noisy
kitchen genuinely needs a slower, clearer delivery) is never left to an
LLM's own discretion to remember or forget per call.

**Elder mode is read directly off `contracts.graph_types.PersonRole.
ELDER`** — no new `Person` field was needed (the roster already models
this distinction structurally). **Noisy-environment mode is a per-turn
runtime signal**, not a static person attribute (a kitchen is not always
noisy) — the caller (the WebSocket client, via `session_manager.py`'s own
turn contract) supplies it per turn; there is no automatic noise/SNR
detection in this phase's scope, stated plainly rather than implied.
"""

from __future__ import annotations

from contracts.graph_types import LanguageProfile, PersonRole

from .types import PacingProfile

_LANGUAGE_CODES: dict[str, str] = {
    "en": "en-US",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "es": "es-US",
}
"""BCP-47 tags for spec §14.2's fixed four-language set — `SpeechConfig.
language_code`'s expected shape. An unrecognised code falls back to
`"en-US"` (see `language_code_for`) rather than raising — a language hint
mismatch degrades gracefully to auto-detection-adjacent behaviour, it
never blocks a response from being spoken at all."""

_DEFAULT_STYLE = "In a warm, natural, conversational pace"
_ELDER_STYLE = "Slowly, clearly, and gently, with a distinct pause between each sentence"
_NOISY_STYLE = "Loudly and clearly, over background noise, with a distinct pause between each sentence"
_ELDER_AND_NOISY_STYLE = (
    "Slowly, loudly, and very clearly, with a distinct pause between each sentence, as if speaking to "
    "someone hard of hearing in a noisy room"
)


def language_code_for(language: str) -> str:
    """Resolves a `SupportedLanguage` code to its BCP-47 tag, defaulting to
    `"en-US"` for anything unrecognised (never raises — a response is
    always speakable)."""
    return _LANGUAGE_CODES.get(language, "en-US")


def pacing_profile_for(
    *,
    language: str,
    role: PersonRole | None,
    noisy_environment: bool,
    language_profile: LanguageProfile | None,
) -> PacingProfile:
    """Computes the real `PacingProfile` for one response.

    Args:
        language: the response's own language code (may differ from the
            speaker's `primary_language` for a household member who
            understands but does not speak a given language — the
            response is always paced for *this* language's rendering).
        role: the listener's `contracts.graph_types.PersonRole`, when
            known (`None` for an unidentified speaker — A66's own
            "unknown speaker" path, which is restricted to R0/R1 responses
            anyway; pacing still degrades sensibly to the default rather
            than guessing an elder profile).
        noisy_environment: a per-turn caller-supplied hint (see module
            docstring) — never inferred automatically this phase.
        language_profile: the listener's `LanguageProfile`, when known.
            `formality_preference` is not yet folded into the pacing
            instruction itself (that is A69's own prompt's job, via
            `speaker_language`/register, not this deterministic policy's)
            — accepted here for the constructor's own forward-compatible
            shape, most directly so a caller never has to special-case
            "no profile at all" differently from "a profile with no
            useful pacing signal."
    """
    is_elder = role is PersonRole.ELDER
    # `language_profile` is accepted for this function's forward-compatible
    # shape (see docstring) but not yet consulted by the pacing policy
    # itself — formality/register belongs to A69's own prompt, not this
    # deterministic policy.
    _ = language_profile

    if is_elder and noisy_environment:
        style = _ELDER_AND_NOISY_STYLE
    elif is_elder:
        style = _ELDER_STYLE
    elif noisy_environment:
        style = _NOISY_STYLE
    else:
        style = _DEFAULT_STYLE

    return PacingProfile(style_instruction=style, language_code=language_code_for(language))


__all__ = ["language_code_for", "pacing_profile_for"]

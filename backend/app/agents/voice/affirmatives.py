"""The canonical, enumerated affirmative-phrase table — A68 Confirmation
Agent's deterministic first layer (spec §14.6 rule 4: "approval by voice
requires an explicit affirmative. Silence, ambiguity, or a non-committal
response is treated as *not approved*").

**Why a fixed table, not an LLM judgment call, per gharos-standards and
this phase's own dispatch instructions:** "so the 'never silence-as-
approval' rule holds even if the LLM call fails or returns something
unexpected." `confirmation_agent.ConfirmationAgent.evaluate_response`
checks a spoken response against this table *before* any model call is
made — a response matching nothing here is `confirmed=False`, full stop,
with zero Gemini calls in the loop at all (cost discipline mirrors
`app.agents.fair_allocator.load_monitor_agent`'s "nothing to narrate"
precedent, and safety discipline mirrors `app.agents.concierge.
confirmation_verifier_agent`'s structural-first, semantic-second design:
a Pro-tier semantic check can only run, and can only ever narrow an
already-matched affirmative to `False` — e.g. catching "haan, lekin abhi
nahi" ("yes, but not now") — never turn a non-match into `True`).

**Extensible, per-language, never a single global list.** New phrases are
added here as real household usage surfaces them (per ADR-020's language
depth split: English/Hindi get iterated depth, Marathi/Spanish get the
same mechanism at demonstration breadth). Every entry is lowercase,
casefolded-comparison-ready; matching is done by `check_affirmative`
below via whole-word/phrase boundaries, never bare substring containment
(a bare `"ha"` token, for instance, is deliberately excluded — too short
to safely word-boundary-match without false positives inside unrelated
words in a romanised transliteration).
"""

from __future__ import annotations

import re

AFFIRMATIVE_PHRASES: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "yes",
            "yeah",
            "yep",
            "yup",
            "sure",
            "ok",
            "okay",
            "confirm",
            "confirmed",
            "correct",
            "affirmative",
            "go ahead",
            "do it",
            "please do",
            "that's right",
            "sounds good",
        }
    ),
    "hi": frozenset(
        {
            "haan",
            "han",
            "haanji",
            "hanji",
            "haan ji",
            "haan bilkul",
            "bilkul",
            "theek hai",
            "thik hai",
            "sahi hai",
            "kar do",
            "kardo",
            "kar dijiye",
            "haan kar do",
            "haan sahi hai",
        }
    ),
    "mr": frozenset(
        {
            "ho",
            "hoy",
            "houy",
            "barobar",
            "kara",
            "chalte",
            "theek ahe",
            "thik ahe",
            "ho chalel",
            "kara mag",
        }
    ),
    "es": frozenset(
        {
            "si",
            "sí",
            "vale",
            "claro",
            "de acuerdo",
            "correcto",
            "confirmo",
            "por supuesto",
            "está bien",
            "esta bien",
        }
    ),
}
"""Per-language canonical affirmative tables (spec §14.2's fixed four
languages — ADR-020 Decision 2's depth split does not exempt Marathi or
Spanish from this safety-critical table, only from *tuning* time)."""


def _normalize(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def check_affirmative(response_text: str | None, *, language: str) -> str | None:
    """Checks `response_text` against the canonical affirmative table for
    `language`, always also checking the English table (a code-mixed
    household routinely answers "ok"/"yes" regardless of which language
    the read-back was spoken in — spec §14.2's own "one family... three
    languages" framing).

    Args:
        response_text: the household member's real spoken response,
            already ASR-transcribed. `None` or whitespace-only is treated
            as silence — never matched (spec §14.6 rule 4).
        language: the read-back's language code (`"en"`, `"hi"`, `"mr"`,
            or `"es"`) — an unrecognised code still checks the English
            table alone, never raises.

    Returns:
        The exact canonical phrase matched, or `None` if nothing in the
        applicable table(s) matches `response_text` as a whole word/phrase.
        `None` (not a matched phrase) is the entire proof that silence and
        an unrecognised utterance are indistinguishable from "not
        confirmed" at this layer — by construction, not by convention.
    """
    if response_text is None:
        return None
    normalized = _normalize(response_text)
    if not normalized:
        return None

    candidate_phrases: set[str] = set(AFFIRMATIVE_PHRASES.get("en", frozenset()))
    candidate_phrases |= set(AFFIRMATIVE_PHRASES.get(language, frozenset()))

    # Longest phrases first, so a multi-word phrase ("theek hai") is
    # preferred over accidentally matching a shorter phrase nested inside
    # a longer non-matching sentence for reporting purposes; matching
    # correctness itself does not depend on order (any match at all is a
    # match), but this keeps the reported `matched_affirmative_phrase`
    # the most specific one found.
    for phrase in sorted(candidate_phrases, key=len, reverse=True):
        pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
        if re.search(pattern, normalized):
            return phrase
    return None


__all__ = ["AFFIRMATIVE_PHRASES", "check_affirmative"]

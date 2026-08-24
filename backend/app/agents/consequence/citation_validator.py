"""Citation location and validation — the single most safety-critical
mechanism in Phase 4 (PHASES.md §4, spec §7.6: "every `implies` edge must
cite a source span; uncitable -> discarded").

**Design choice, deliberate:** A12 does not ask the model for a byte
offset and then check it — LLMs are unreliable at byte/character
arithmetic, and trusting a model-reported offset would make "citation
required" a formality the model can satisfy by printing any two numbers.
Instead, the model is asked only for the literal text it is citing
(`claimed_span_text`), and *this module* locates that text for real inside
the actual document and computes the byte-offset region itself. A
candidate whose claimed span text cannot be located in the real document —
because the model paraphrased instead of quoting, or fabricated the
citation outright — is **not locatable**, and `implication_agent.py`
discards it before it ever becomes an `ImpliedObligationCandidate`. This
is what makes "uncitable -> discarded" structural rather than a prompt
instruction the model can ignore.

Deliberately pure and I/O-free: operates on plain strings, not a
`GraphReader`/`RawPayloadStore` — trivially testable with adversarial
fixtures, no graph or network required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WHITESPACE_PATTERN = re.compile(r"\s+")
_WORD_PATTERN = re.compile(r"\S+")

_MAX_SPAN_FRACTION_OF_DOCUMENT = 0.6
"""A located span covering more than 60% of the whole document is not a
specific citation — it is "cite the whole email," which would trivially
"support" any claim and defeats the point of requiring one. Rejected
regardless of how well it matches."""

_MIN_CLAIMED_SPAN_CHARACTERS = 3
"""A claimed span shorter than this cannot meaningfully support a claim."""

_MIN_TOKEN_OVERLAP_RATIO = 0.6
"""Similarity floor for the fuzzy token-window fallback search (handles
minor whitespace/punctuation paraphrasing of an otherwise real quote) — a
best-effort window below this ratio is treated as not located at all."""


@dataclass(frozen=True, slots=True)
class LocatedCitation:
    """A claimed span the model cited, successfully located inside the
    real document text — the byte-offset region and the exact resolved
    text at that region, ready to become a `contracts.agents.Citation` +
    `contracts.graph_types.SourceRef`-shaped region string."""

    region: str
    """`"<start>-<end>"` — half-open byte-offset span into
    `document_text.encode("utf-8")`, matching
    `app.persistence.region_resolver`'s Convention 1 exactly, so this
    citation is resolvable by the same machinery every other extracted
    field's region is."""
    resolved_text: str


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    """The outcome of locating+validating one claimed span against one
    document's real text. `valid=False` always carries a specific,
    human-readable `reason` — never a bare boolean."""

    valid: bool
    located: LocatedCitation | None
    reason: str | None


def _normalize(text: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", text).strip().lower()


def _char_span_to_byte_region(document_text: str, start_char: int, end_char: int) -> str:
    start_byte = len(document_text[:start_char].encode("utf-8"))
    end_byte = len(document_text[:end_char].encode("utf-8"))
    return f"{start_byte}-{end_byte}"


def _try_exact_match(claimed_span_text: str, document_text: str) -> tuple[int, int] | None:
    """Case-sensitive, then case-insensitive, exact substring search —
    covers the common case of a model quoting verbatim or near-verbatim."""
    index = document_text.find(claimed_span_text)
    if index != -1:
        return index, index + len(claimed_span_text)

    lowered_doc = document_text.lower()
    lowered_claim = claimed_span_text.lower()
    index = lowered_doc.find(lowered_claim)
    if index != -1:
        return index, index + len(claimed_span_text)
    return None


def _try_fuzzy_window_match(claimed_span_text: str, document_text: str) -> tuple[int, int] | None:
    """Fallback for minor whitespace/punctuation paraphrasing: slides a
    window of consecutive whitespace-delimited words across the document
    matching the claimed span's word count, and returns the best-overlap
    window if it clears `_MIN_TOKEN_OVERLAP_RATIO`. Real document sizes in
    this system (an email, a chat export, a notice) are small enough that
    an O(n * window) scan is fine — no document here is book-length."""
    claim_tokens = _normalize(claimed_span_text).split()
    if not claim_tokens:
        return None

    words = list(_WORD_PATTERN.finditer(document_text))
    window_size = len(claim_tokens)
    if window_size == 0 or window_size > len(words):
        return None

    claim_token_set = set(claim_tokens)
    best_ratio = 0.0
    best_span: tuple[int, int] | None = None
    for start_index in range(0, len(words) - window_size + 1):
        window_words = words[start_index : start_index + window_size]
        window_text = document_text[window_words[0].start() : window_words[-1].end()]
        window_token_set = set(_normalize(window_text).split())
        if not window_token_set:
            continue
        union = claim_token_set | window_token_set
        overlap = len(claim_token_set & window_token_set) / len(union) if union else 0.0
        if overlap > best_ratio:
            best_ratio = overlap
            best_span = (window_words[0].start(), window_words[-1].end())

    if best_span is not None and best_ratio >= _MIN_TOKEN_OVERLAP_RATIO:
        return best_span
    return None


def locate_and_validate_citation(
    *,
    claimed_span_text: str,
    document_text: str,
) -> CitationValidationResult:
    """Locates `claimed_span_text` inside `document_text` and validates
    the result is a real, specific citation.

    Args:
        claimed_span_text: the literal text the model claims supports its
            inference — never a paraphrase the model was asked to produce;
            the prompt instructs "quote verbatim."
        document_text: the real, full SOURCE_DOCUMENT text (decoded
            UTF-8) this span is claimed to come from.

    Returns:
        A `CitationValidationResult`. `valid=True` carries a
        `LocatedCitation` with a real, resolvable byte-offset region.
        Never raises — a span that cannot be located is a normal,
        expected "discard this candidate" outcome, not an exceptional
        one.
    """
    stripped_claim = claimed_span_text.strip()
    if len(stripped_claim) < _MIN_CLAIMED_SPAN_CHARACTERS:
        return CitationValidationResult(
            valid=False, located=None, reason=f"claimed span text is too short: {stripped_claim!r}"
        )

    span = _try_exact_match(claimed_span_text, document_text) or _try_fuzzy_window_match(
        claimed_span_text, document_text
    )
    if span is None:
        return CitationValidationResult(
            valid=False,
            located=None,
            reason=f"claimed span text not found anywhere in the source document: {claimed_span_text!r}",
        )

    start_char, end_char = span
    document_length_bytes = len(document_text.encode("utf-8"))
    region = _char_span_to_byte_region(document_text, start_char, end_char)
    resolved_text = document_text[start_char:end_char]

    span_fraction = (
        (len(resolved_text.encode("utf-8")) / document_length_bytes) if document_length_bytes else 1.0
    )
    if span_fraction > _MAX_SPAN_FRACTION_OF_DOCUMENT:
        return CitationValidationResult(
            valid=False,
            located=None,
            reason=(
                f"located span covers {span_fraction:.0%} of the document — not a specific citation "
                f"(floor: {_MAX_SPAN_FRACTION_OF_DOCUMENT:.0%})"
            ),
        )

    return CitationValidationResult(
        valid=True, located=LocatedCitation(region=region, resolved_text=resolved_text), reason=None
    )


__all__ = ["CitationValidationResult", "LocatedCitation", "locate_and_validate_citation"]

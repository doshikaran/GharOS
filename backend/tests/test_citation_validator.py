"""Tests for `app.agents.consequence.citation_validator` — the single
most safety-critical mechanism in Phase 4 (spec §7.6: "every implies edge
must cite a source span; uncitable -> discarded").

Pure unit tests, no Gemini, no graph, no emulator — this module is
deliberately I/O-free (see its own docstring).
"""

from __future__ import annotations

from app.agents.consequence.citation_validator import locate_and_validate_citation

_DOCUMENT = (
    "Field trip Friday. Signed permission slip due Wednesday. Fee is Rs. 500. "
    "Nut-free lunch required for all students. Early pickup at 1:30pm for the "
    "field trip group."
)


class TestExactMatch:
    def test_exact_verbatim_span_is_located(self) -> None:
        result = locate_and_validate_citation(
            claimed_span_text="Signed permission slip due Wednesday", document_text=_DOCUMENT
        )
        assert result.valid is True
        assert result.located is not None
        assert result.located.resolved_text == "Signed permission slip due Wednesday"
        start, end = (int(part) for part in result.located.region.split("-"))
        assert _DOCUMENT.encode("utf-8")[start:end].decode("utf-8") == "Signed permission slip due Wednesday"

    def test_case_insensitive_match_is_located(self) -> None:
        result = locate_and_validate_citation(
            claimed_span_text="NUT-FREE LUNCH REQUIRED", document_text=_DOCUMENT
        )
        assert result.valid is True
        assert result.located is not None


class TestFuzzyWindowMatch:
    def test_minor_whitespace_paraphrase_is_located(self) -> None:
        result = locate_and_validate_citation(
            claimed_span_text="Early pickup at  1:30pm  for the field trip group",
            document_text=_DOCUMENT,
        )
        assert result.valid is True


class TestUncitableDiscarding:
    """The mandatory rule: an uncitable inference is discarded, never
    surfaced. These are the adversarial cases."""

    def test_fabricated_span_not_in_document_is_rejected(self) -> None:
        result = locate_and_validate_citation(
            claimed_span_text="The school will provide a bus with air conditioning",
            document_text=_DOCUMENT,
        )
        assert result.valid is False
        assert result.located is None
        assert result.reason is not None

    def test_paraphrase_not_a_real_quote_is_rejected(self) -> None:
        """A model that paraphrases instead of quoting verbatim must not
        be treated as having cited anything — this is the exact failure
        mode the module's docstring names as the reason offsets are
        computed here, not trusted from the model."""
        result = locate_and_validate_citation(
            claimed_span_text="The permission form needs a parent's signature by midweek",
            document_text=_DOCUMENT,
        )
        assert result.valid is False

    def test_too_short_claimed_span_is_rejected(self) -> None:
        result = locate_and_validate_citation(claimed_span_text="Fe", document_text=_DOCUMENT)
        assert result.valid is False
        assert "too short" in (result.reason or "")

    def test_whole_document_span_is_rejected_as_not_specific(self) -> None:
        result = locate_and_validate_citation(claimed_span_text=_DOCUMENT, document_text=_DOCUMENT)
        assert result.valid is False
        assert "specific citation" in (result.reason or "")


class TestByteOffsetConvention:
    def test_region_is_half_open_byte_offset_matching_region_resolver_convention(self) -> None:
        from app.persistence.region_resolver import TextSpanRegion, parse_region

        result = locate_and_validate_citation(claimed_span_text="Fee is Rs. 500.", document_text=_DOCUMENT)
        assert result.valid is True
        assert result.located is not None
        parsed = parse_region(result.located.region)
        assert isinstance(parsed, TextSpanRegion)

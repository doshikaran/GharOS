"""Tests for `app.agents.voice.affirmatives.check_affirmative` — the
deterministic, enumerated affirmative-phrase table A68 Confirmation Agent
checks *before* any model call (spec §14.6 rule 4: silence or ambiguity
is never approval)."""

from __future__ import annotations

from app.agents.voice.affirmatives import check_affirmative


class TestSilenceNeverMatches:
    def test_none_response_does_not_match(self) -> None:
        assert check_affirmative(None, language="hi") is None

    def test_empty_response_does_not_match(self) -> None:
        assert check_affirmative("", language="hi") is None

    def test_whitespace_only_response_does_not_match(self) -> None:
        assert check_affirmative("   \n\t  ", language="en") is None


class TestExplicitAffirmativesMatch:
    def test_english_yes_matches(self) -> None:
        assert check_affirmative("Yes", language="en") == "yes"

    def test_hindi_haan_matches(self) -> None:
        assert check_affirmative("haan kar do", language="hi") is not None

    def test_marathi_ho_matches(self) -> None:
        assert check_affirmative("ho, barobar aahe", language="mr") is not None

    def test_spanish_si_matches(self) -> None:
        assert check_affirmative("sí, claro", language="es") is not None

    def test_english_fallback_matches_regardless_of_turn_language(self) -> None:
        """A code-mixed household routinely answers plain English "ok"
        even mid-Hindi-turn — spec §14.2's "one family, three languages"
        framing."""
        assert check_affirmative("ok theek hai", language="hi") is not None


class TestNonAffirmativesDoNotMatch:
    def test_ambiguous_reply_does_not_match(self) -> None:
        assert check_affirmative("pata nahi, shayad", language="hi") is None

    def test_negative_reply_does_not_match(self) -> None:
        assert check_affirmative("nahi, mat karo", language="hi") is None

    def test_unrelated_reply_does_not_match(self) -> None:
        assert check_affirmative("kal baat karte hain", language="hi") is None

    def test_short_ha_syllable_is_not_a_recognised_token(self) -> None:
        """"ha" alone is deliberately excluded from the table — too short
        to safely word-boundary-match without false positives; a real
        household response using it alone should not silently confirm."""
        assert check_affirmative("ha", language="hi") is None


class TestWordBoundaryMatching:
    def test_affirmative_substring_inside_unrelated_word_does_not_match(self) -> None:
        """"ho" (Marathi yes) must not match merely because it appears as
        a substring inside an unrelated longer word."""
        assert check_affirmative("household chores", language="mr") is None

"""Tests for `app.voice.pacing` — A69's deterministic pacing policy
(spec §15.11 A69: "pacing adapted to the listener")."""

from __future__ import annotations

from contracts.graph_types import PersonRole

from app.voice.pacing import language_code_for, pacing_profile_for


class TestLanguageCodeFor:
    def test_known_codes_map_to_bcp47(self) -> None:
        assert language_code_for("hi") == "hi-IN"
        assert language_code_for("mr") == "mr-IN"
        assert language_code_for("es") == "es-US"
        assert language_code_for("en") == "en-US"

    def test_unknown_code_falls_back_to_english_never_raises(self) -> None:
        assert language_code_for("xx") == "en-US"


class TestPacingProfileFor:
    def test_default_profile_for_a_non_elder_quiet_environment(self) -> None:
        profile = pacing_profile_for(
            language="en", role=PersonRole.ADULT, noisy_environment=False, language_profile=None
        )
        lowered = profile.style_instruction.lower()
        assert "warm" in lowered or "conversational" in lowered
        assert profile.language_code == "en-US"

    def test_elder_role_gets_slow_clear_pacing(self) -> None:
        profile = pacing_profile_for(
            language="hi", role=PersonRole.ELDER, noisy_environment=False, language_profile=None
        )
        assert "slowly" in profile.style_instruction.lower()

    def test_noisy_environment_gets_loud_clear_pacing(self) -> None:
        profile = pacing_profile_for(
            language="en", role=PersonRole.ADULT, noisy_environment=True, language_profile=None
        )
        assert "loudly" in profile.style_instruction.lower()

    def test_elder_and_noisy_combine(self) -> None:
        profile = pacing_profile_for(
            language="en", role=PersonRole.ELDER, noisy_environment=True, language_profile=None
        )
        assert "slowly" in profile.style_instruction.lower()
        assert "loudly" in profile.style_instruction.lower()

    def test_unidentified_speaker_role_none_never_crashes(self) -> None:
        profile = pacing_profile_for(
            language="en", role=None, noisy_environment=False, language_profile=None
        )
        assert profile.language_code == "en-US"


__all__: list[str] = []

"""Tests for `app.agents.voice.formatting.format_inr` — the deterministic
Indian-digit-group currency formatter A65/A68 both rely on for the
safety-critical "amounts read digit-grouped" rule (spec §14.6 rule 2).
"""

from __future__ import annotations

import pytest

from app.agents.voice.formatting import format_inr


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (500, "₹500"),
        (3500, "₹3,500"),
        (12345, "₹12,345"),
        (100000, "₹1,00,000"),  # 1 lakh
        (300000, "₹3,00,000"),  # 3 lakh
        (1234567, "₹12,34,567"),
        (20000000, "₹2,00,00,000"),  # 2 crore
        (-3500, "-₹3,500"),
    ],
)
def test_format_inr_indian_digit_grouping(amount: float, expected: str) -> None:
    assert format_inr(amount) == expected


def test_format_inr_rounds_fractional_paise() -> None:
    assert format_inr(3499.6) == "₹3,500"

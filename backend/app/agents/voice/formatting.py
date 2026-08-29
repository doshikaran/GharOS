"""Deterministic Indian-digit-group currency formatting — shared by A65
Normalisation (produces `NormalizedSpan.amount_display`) and A68
Confirmation (structurally checks its own generated read-back text
literally contains this exact string, spec §14.6 rule 2: "amounts are
read digit-grouped and repeated").

Deliberately plain code, not a model output: spec's own worked example
("saade teen hazaar" -> "₹3,500 — three thousand five hundred") is
arithmetic-plus-formatting once the numeric value is known, and this
codebase's established discipline (`app.solvers.salary_calculator`,
`app.solvers.calibration_stats`) is that arithmetic is always delegated
to a deterministic tool, never left to a model to get subtly wrong on a
money path (gharos-standards: "100% [test coverage] on anything in the
money or safety path").
"""

from __future__ import annotations


def format_inr(amount: float) -> str:
    """Formats `amount` using the Indian numbering system (lakh/crore
    grouping: 3 digits, then groups of 2), e.g. `3500` -> `"₹3,500"`,
    `300000` -> `"₹3,00,000"` (3 lakh), `20000000` -> `"₹2,00,00,000"`
    (2 crore).

    Args:
        amount: a non-negative-or-negative rupee amount. Fractional paise
            are rounded to the nearest rupee for read-back purposes (spoken
            household amounts are never paise-precision) — the underlying
            `NormalizedSpan.amount_value` retains full precision; only this
            display string rounds.

    Returns:
        The `"₹"`-prefixed, digit-grouped string.
    """
    rounded = round(amount)
    sign = "-" if rounded < 0 else ""
    digits = str(abs(rounded))

    if len(digits) <= 3:
        return f"{sign}₹{digits}"

    last_three = digits[-3:]
    remainder = digits[:-3]
    groups: list[str] = []
    while len(remainder) > 2:
        groups.insert(0, remainder[-2:])
        remainder = remainder[:-2]
    if remainder:
        groups.insert(0, remainder)

    grouped = ",".join(groups) + "," + last_three
    return f"{sign}₹{grouped}"


__all__ = ["format_inr"]

"""Deterministic product-category normalisation for receipt line items
(spec §5.4.2 RECEIPT: "product-category normalisation across merchants —
so 'AMUL TAAZA 1L' and 'Milk 1 litre' resolve to the same category").

Deliberately **not** an LLM call: category assignment is a lookup problem
over a bounded, auditable keyword set, not a judgment call — a deterministic
function is cheaper, faster, trivially unit-testable, and never varies
between two runs on the same input the way a model call could. A3b
(`line_item_extraction.py`) calls `normalize_category` on every line item
description Gemini reads off the receipt; Gemini itself is never asked to
invent the category.
"""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[a-z]+")

# Ordered (first match wins) keyword -> canonical category. Keywords are
# lowercase substrings checked against a lowercased, alphabetic-only token
# set from the description — deliberately narrow and inspectable rather
# than a fuzzy/ML classifier, so a household member (or a test) can see
# exactly why "AMUL TAAZA 1L" and "Milk 1 litre" both land on
# "dairy_and_milk".
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dairy_and_milk", ("milk", "taaza", "curd", "dahi", "paneer", "cheese", "butter", "ghee", "yogurt")),
    ("bakery", ("bread", "bun", "pav", "bakery", "cake", "biscuit", "cookie")),
    ("produce", ("vegetable", "veggies", "fruit", "onion", "tomato", "potato", "banana", "apple")),
    ("staples_and_grocery", ("rice", "atta", "flour", "dal", "pulses", "sugar", "salt", "oil", "masala")),
    ("beverages", ("juice", "soda", "cola", "water", "tea", "coffee", "chai")),
    ("snacks", ("chips", "namkeen", "chocolate", "candy", "snack")),
    ("household", ("detergent", "soap", "cleaner", "tissue", "toothpaste", "shampoo")),
    ("pharmacy", ("tablet", "syrup", "medicine", "pharmacy", "paracetamol", "bandage")),
    ("fuel", ("petrol", "diesel", "fuel")),
    ("dining", ("meal", "combo", "burger", "pizza", "thali")),
)


def normalize_category(description: str) -> str | None:
    """Maps a raw, merchant-specific line-item description to a canonical
    product category via keyword matching.

    Args:
        description: the raw description as printed on the receipt (any
            case, any language mix — this function only recognises the
            English/romanized keyword set above; a description with none
            of them yields `None` rather than a guessed category).

    Returns:
        A canonical category string, or `None` if no keyword matched —
        `None` is a legitimate, honest result (spec's "never guess"
        discipline applies here too: an unrecognised item is left
        uncategorised, never forced into an arbitrary bucket).
    """
    lowered = description.lower()
    tokens = set(_WORD_PATTERN.findall(lowered))
    for category, keywords in _CATEGORY_KEYWORDS:
        for keyword in keywords:
            if keyword in tokens or keyword in lowered:
                return category
    return None


__all__ = ["normalize_category"]

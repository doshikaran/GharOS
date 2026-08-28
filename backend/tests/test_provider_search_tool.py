"""Tests for `app.tools.provider_search_tool.ProviderSearchTool` — the
honestly-labeled synthetic discovery source A51 uses (PHASES.md Phase
10).
"""

from __future__ import annotations

from typing import Any

import pytest
from contracts.errors import ToolFailure
from contracts.tools import PermissionTier

from app.tools.provider_search_tool import ProviderSearchTool, SyntheticProviderListing


def _listings(result: Any) -> tuple[SyntheticProviderListing, ...]:
    assert isinstance(result.value, tuple)
    assert all(isinstance(item, SyntheticProviderListing) for item in result.value)
    return result.value


class TestToolIdentity:
    def test_tier_is_t1(self) -> None:
        tool = ProviderSearchTool()
        assert tool.tier is PermissionTier.T1_SEARCH


class TestDeterministicSynthesis:
    def test_same_inputs_produce_the_same_listings_every_run(self) -> None:
        tool = ProviderSearchTool()
        first = tool.invoke(category="dentist", location_context="home", count=3)
        second = tool.invoke(category="dentist", location_context="home", count=3)
        assert first.ok is True
        assert second.ok is True
        assert first.value == second.value

    def test_returns_exactly_count_listings(self) -> None:
        tool = ProviderSearchTool()
        result = tool.invoke(category="plumber", location_context="office", count=5)
        assert result.ok is True
        assert isinstance(result.value, tuple)
        assert len(result.value) == 5
        assert all(isinstance(item, SyntheticProviderListing) for item in result.value)

    def test_every_listing_is_labeled_synthetic(self) -> None:
        tool = ProviderSearchTool()
        result = tool.invoke(category="dentist", location_context="home", count=2)
        assert result.ok is True
        assert all(listing.source == "synthetic_directory" for listing in _listings(result))

    def test_different_categories_produce_different_listings(self) -> None:
        tool = ProviderSearchTool()
        dentist = _listings(tool.invoke(category="dentist", location_context="home", count=1))[0]
        plumber = _listings(tool.invoke(category="plumber", location_context="home", count=1))[0]
        assert dentist.name != plumber.name

    def test_ratings_and_distances_are_within_plausible_bounds(self) -> None:
        tool = ProviderSearchTool()
        result = tool.invoke(category="dentist", location_context="home", count=10)
        for listing in _listings(result):
            assert 3.5 <= listing.rating <= 5.0
            assert 0.5 <= listing.distance_km <= 8.0
            assert listing.price_band in ("$", "$$", "$$$")
            assert listing.specialisations


class TestValidation:
    def test_missing_category_raises_tool_failure(self) -> None:
        tool = ProviderSearchTool()
        with pytest.raises(ToolFailure):
            tool.invoke(location_context="home", count=1)

    def test_blank_location_context_raises_tool_failure(self) -> None:
        tool = ProviderSearchTool()
        with pytest.raises(ToolFailure):
            tool.invoke(category="dentist", location_context="   ", count=1)

    def test_non_positive_count_raises_tool_failure(self) -> None:
        tool = ProviderSearchTool()
        with pytest.raises(ToolFailure):
            tool.invoke(category="dentist", location_context="home", count=0)

    def test_bool_count_is_rejected(self) -> None:
        tool = ProviderSearchTool()
        with pytest.raises(ToolFailure):
            tool.invoke(category="dentist", location_context="home", count=True)

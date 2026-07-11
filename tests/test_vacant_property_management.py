"""管理画面向け居抜き物件管理ロジック（vacant_property_management.py）の単体テスト。"""

from __future__ import annotations

from datetime import datetime

import pytest

from regional_revitalization.models import GeoPoint
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    VacantPropertyCandidate,
)
from regional_revitalization.vacant_property_management import (
    search_vacant_properties_in_bounds,
    update_vacant_property_details,
)


def _make_candidate(place_id: str, lat: float = 35.68, lng: float = 139.76) -> VacantPropertyCandidate:
    return VacantPropertyCandidate(
        place_id=place_id,
        name="テスト店舗",
        location=GeoPoint(latitude=lat, longitude=lng),
        business_status=BusinessStatus.CLOSED_PERMANENTLY,
        types=["restaurant"],
        address=None,
        phone_number=None,
        data_fetched_at=datetime.now(),
        last_review_time=None,
        estimated_closure_period_start=None,
        estimated_closure_period_end=None,
    )


class TestSearchVacantPropertiesInBounds:
    def test_returns_candidates_within_bounds(self) -> None:
        inside = _make_candidate("p1", lat=35.0, lng=139.0)
        outside = _make_candidate("p2", lat=40.0, lng=145.0)
        repo = InMemoryVacantPropertyRepository([inside, outside])

        results = search_vacant_properties_in_bounds(repo, 34.0, 138.0, 36.0, 140.0, 10)
        assert results == [inside]

    def test_rejects_invalid_limit(self) -> None:
        repo = InMemoryVacantPropertyRepository()
        with pytest.raises(ValueError, match="limit"):
            search_vacant_properties_in_bounds(repo, 34.0, 138.0, 36.0, 140.0, 0)


class TestUpdateVacantPropertyDetails:
    def test_updates_details(self) -> None:
        candidate = _make_candidate("p1")
        repo = InMemoryVacantPropertyRepository([candidate])

        update_vacant_property_details(repo, "p1", 150000, 45.5, 2010, "鉄骨造")

        updated = repo.get_by_place_id("p1")
        assert updated.rent_yen == 150000
        assert updated.area_sqm == 45.5
        assert updated.built_year == 2010
        assert updated.structure == "鉄骨造"

    def test_can_clear_values_with_none(self) -> None:
        candidate = _make_candidate("p1")
        repo = InMemoryVacantPropertyRepository([candidate])
        update_vacant_property_details(repo, "p1", 150000, 45.5, 2010, "鉄骨造")

        update_vacant_property_details(repo, "p1", None, None, None, None)
        updated = repo.get_by_place_id("p1")
        assert updated.rent_yen is None

    def test_rejects_negative_rent(self) -> None:
        candidate = _make_candidate("p1")
        repo = InMemoryVacantPropertyRepository([candidate])
        with pytest.raises(ValueError, match="rent_yen"):
            update_vacant_property_details(repo, "p1", -100, None, None, None)

    def test_raises_for_unknown_place_id(self) -> None:
        repo = InMemoryVacantPropertyRepository()
        with pytest.raises(ValueError, match="見つかりません"):
            update_vacant_property_details(repo, "unknown", None, None, None, None)

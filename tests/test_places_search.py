"""Places APIリアルタイム検索モジュール（places_search.py）の単体テスト。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from regional_revitalization.models import GeoPoint
from regional_revitalization.places_search import (
    InMemoryPlacesSearchResultRepository,
    MockPlacesSearchClient,
    execute_places_search,
    register_search_result,
)
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    PlaceDetailsResult,
    PlacesApiError,
)


def _make_place_details(place_id: str = "place-1") -> PlaceDetailsResult:
    return PlaceDetailsResult(
        place_id=place_id,
        name="テスト店舗",
        location=GeoPoint(latitude=35.68, longitude=139.76),
        business_status=BusinessStatus.CLOSED_PERMANENTLY,
        types=["restaurant"],
        address="東京都渋谷区",
        phone_number=None,
        latest_review_time=None,
    )


class TestExecutePlacesSearch:
    async def test_saves_results_as_unregistered(self) -> None:
        client = MockPlacesSearchClient(results=[_make_place_details()])
        result_repo = InMemoryPlacesSearchResultRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        results = await execute_places_search(
            client, result_repo, location, 1.0, "レストラン", None
        )
        assert len(results) == 1
        assert results[0].is_registered is False
        assert len(result_repo) == 1

    async def test_rejects_non_positive_radius(self) -> None:
        client = MockPlacesSearchClient(results=[])
        result_repo = InMemoryPlacesSearchResultRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        with pytest.raises(ValueError, match="radius_km"):
            await execute_places_search(client, result_repo, location, 0, None, None)

    async def test_propagates_places_api_error(self) -> None:
        client = MockPlacesSearchClient(should_error=True)
        result_repo = InMemoryPlacesSearchResultRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        with pytest.raises(PlacesApiError):
            await execute_places_search(client, result_repo, location, 1.0, None, None)


class TestRegisterSearchResult:
    async def test_registers_result_as_vacant_property(self) -> None:
        client = MockPlacesSearchClient(results=[_make_place_details()])
        result_repo = InMemoryPlacesSearchResultRepository()
        vacant_repo = InMemoryVacantPropertyRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        results = await execute_places_search(
            client, result_repo, location, 1.0, None, None
        )
        candidate = await register_search_result(
            result_repo, vacant_repo, results[0].result_id
        )
        assert candidate.place_id == "place-1"
        assert len(vacant_repo) == 1

        updated_result = await result_repo.get_by_id(results[0].result_id)
        assert updated_result.is_registered is True

    async def test_raises_for_unknown_result(self) -> None:
        result_repo = InMemoryPlacesSearchResultRepository()
        vacant_repo = InMemoryVacantPropertyRepository()
        with pytest.raises(ValueError, match="見つかりません"):
            await register_search_result(result_repo, vacant_repo, uuid4())

    async def test_raises_if_already_registered(self) -> None:
        client = MockPlacesSearchClient(results=[_make_place_details()])
        result_repo = InMemoryPlacesSearchResultRepository()
        vacant_repo = InMemoryVacantPropertyRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        results = await execute_places_search(
            client, result_repo, location, 1.0, None, None
        )
        await register_search_result(result_repo, vacant_repo, results[0].result_id)

        with pytest.raises(ValueError, match="既に登録済み"):
            await register_search_result(result_repo, vacant_repo, results[0].result_id)

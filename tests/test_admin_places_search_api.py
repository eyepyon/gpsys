"""管理画面向けPlaces APIリアルタイム検索・居抜き物件管理APIの結合テスト。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from regional_revitalization.admin_auth import (
    InMemoryAdminUserRepository,
    create_admin_user,
)
from regional_revitalization.admin_stats import InMemoryAdminStatsRepository
from regional_revitalization.api import (
    app,
    set_admin_stats_repository,
    set_admin_user_repository,
    set_inference_client,
    set_places_search_client,
    set_places_search_result_repository,
    set_resource_repository,
    set_search_request_repository,
    set_storage_client,
    set_update_request_repository,
    set_vacant_property_repository,
)
from regional_revitalization.models import GeoPoint
from regional_revitalization.places_search import (
    InMemoryPlacesSearchResultRepository,
    MockPlacesSearchClient,
)
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.search_history import InMemorySearchRequestRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.update_request import InMemoryUpdateRequestRepository
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    PlaceDetailsResult,
    VacantPropertyCandidate,
)


def _make_place_details() -> PlaceDetailsResult:
    return PlaceDetailsResult(
        place_id="place-1",
        name="テスト店舗",
        location=GeoPoint(latitude=35.68, longitude=139.76),
        business_status=BusinessStatus.CLOSED_PERMANENTLY,
        types=["restaurant"],
        address="東京都渋谷区",
        phone_number=None,
        latest_review_time=None,
    )


def _make_candidate(place_id: str, lat: float = 35.68, lng: float = 139.76) -> VacantPropertyCandidate:
    return VacantPropertyCandidate(
        place_id=place_id,
        name="既存の候補",
        location=GeoPoint(latitude=lat, longitude=lng),
        business_status=BusinessStatus.CLOSED_PERMANENTLY,
        types=["cafe"],
        address=None,
        phone_number=None,
        data_fetched_at=datetime.now(),
        last_review_time=None,
        estimated_closure_period_start=None,
        estimated_closure_period_end=None,
    )


@pytest.fixture()
def vacant_repo() -> InMemoryVacantPropertyRepository:
    return InMemoryVacantPropertyRepository()


@pytest.fixture(autouse=True)
def _reset_shared_instances(vacant_repo: InMemoryVacantPropertyRepository) -> None:
    from regional_revitalization.inference import MockInferenceClient

    resource_repo = InMemoryResourceRepository()
    admin_repo = InMemoryAdminUserRepository()

    set_resource_repository(resource_repo)
    set_storage_client(InMemoryStorageClient())
    set_inference_client(MockInferenceClient())
    set_vacant_property_repository(vacant_repo)
    set_admin_user_repository(admin_repo)
    set_update_request_repository(InMemoryUpdateRequestRepository())
    set_search_request_repository(InMemorySearchRequestRepository())
    set_places_search_client(MockPlacesSearchClient(results=[_make_place_details()]))
    set_places_search_result_repository(InMemoryPlacesSearchResultRepository())
    set_admin_stats_repository(
        InMemoryAdminStatsRepository(
            resource_repository=resource_repo,
            vacant_property_repository=vacant_repo,
            admin_user_repository=admin_repo,
        )
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


async def _login(client: TestClient) -> str:
    from regional_revitalization.api import get_admin_user_repository

    repo = get_admin_user_repository()
    await create_admin_user(repo, "alice", "password123", "Alice")
    res = client.post(
        "/admin/auth/login", json={"username": "alice", "password": "password123"}
    )
    return res.json()["session_token"]


class TestSearchRequestRecording:
    def test_vacant_property_search_records_history(self, client: TestClient) -> None:
        res = client.post(
            "/vacant-properties/search",
            json={
                "latitude": 35.68,
                "longitude": 139.76,
                "radius_km": 5.0,
                "business_status": "CLOSED_PERMANENTLY",
            },
        )
        assert res.status_code == 200

    async def test_admin_can_list_search_history(self, client: TestClient) -> None:
        client.post(
            "/vacant-properties/search",
            json={
                "latitude": 35.68,
                "longitude": 139.76,
                "radius_km": 5.0,
                "business_status": "CLOSED_PERMANENTLY",
            },
        )
        token = await _login(client)
        res = client.get(
            "/admin/search-requests", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert len(res.json()["search_requests"]) == 1


class TestAdminPlacesSearch:
    async def test_executes_search_and_returns_unregistered_results(
        self, client: TestClient
    ) -> None:
        token = await _login(client)
        res = client.post(
            "/admin/places-search",
            headers={"Authorization": f"Bearer {token}"},
            json={"latitude": 35.68, "longitude": 139.76, "radius_km": 1.0, "keyword": "レストラン"},
        )
        assert res.status_code == 200
        results = res.json()["results"]
        assert len(results) == 1
        assert results[0]["is_registered"] is False

    async def test_register_result_adds_to_vacant_properties(
        self, client: TestClient, vacant_repo: InMemoryVacantPropertyRepository
    ) -> None:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        search_res = client.post(
            "/admin/places-search",
            headers=headers,
            json={"latitude": 35.68, "longitude": 139.76, "radius_km": 1.0},
        )
        result_id = search_res.json()["results"][0]["result_id"]

        register_res = client.post(
            f"/admin/places-search/{result_id}/register", headers=headers
        )
        assert register_res.status_code == 200
        assert register_res.json()["is_registered"] is True
        assert len(vacant_repo) == 1

    def test_requires_authentication(self, client: TestClient) -> None:
        res = client.post(
            "/admin/places-search",
            json={"latitude": 35.68, "longitude": 139.76, "radius_km": 1.0},
        )
        assert res.status_code == 401


class TestAdminVacantPropertyManagement:
    async def test_lists_vacant_properties_in_bounds(
        self, client: TestClient, vacant_repo: InMemoryVacantPropertyRepository
    ) -> None:
        vacant_repo.upsert_by_place_id(_make_candidate("p1", lat=35.0, lng=139.0))
        vacant_repo.upsert_by_place_id(_make_candidate("p2", lat=40.0, lng=145.0))

        token = await _login(client)
        res = client.get(
            "/admin/vacant-properties",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "min_latitude": 34.0,
                "min_longitude": 138.0,
                "max_latitude": 36.0,
                "max_longitude": 140.0,
            },
        )
        assert res.status_code == 200
        assert len(res.json()["vacant_properties"]) == 1

    async def test_updates_property_details(
        self, client: TestClient, vacant_repo: InMemoryVacantPropertyRepository
    ) -> None:
        vacant_repo.upsert_by_place_id(_make_candidate("p1"))
        token = await _login(client)

        res = client.patch(
            "/admin/vacant-properties/p1",
            headers={"Authorization": f"Bearer {token}"},
            json={"rent_yen": 200000, "area_sqm": 50.0, "built_year": 2015, "structure": "RC造"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["rent_yen"] == 200000
        assert body["structure"] == "RC造"

    async def test_returns_404_for_unknown_place_id(self, client: TestClient) -> None:
        token = await _login(client)
        res = client.patch(
            "/admin/vacant-properties/unknown",
            headers={"Authorization": f"Bearer {token}"},
            json={"rent_yen": 100000},
        )
        assert res.status_code == 404

"""管理画面向けデータ更新API（/admin/resources/*）の結合テスト。"""

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
    set_resource_repository,
    set_storage_client,
    set_vacant_property_repository,
)
from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.vacant_property import InMemoryVacantPropertyRepository


def _make_resource(lat: float = 35.68, lng: float = 139.76) -> RegionalResource:
    now = datetime.now()
    return RegionalResource(
        resource_id=uuid4(),
        name="テスト資源",
        category="イベント",
        description="説明文",
        location=GeoPoint(latitude=lat, longitude=lng),
        file_url=None,
        embedding=[0.1, 0.2],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def resource_repo() -> InMemoryResourceRepository:
    return InMemoryResourceRepository()


@pytest.fixture(autouse=True)
def _reset_shared_instances(resource_repo: InMemoryResourceRepository) -> None:
    from regional_revitalization.inference import MockInferenceClient

    vacant_repo = InMemoryVacantPropertyRepository()
    admin_repo = InMemoryAdminUserRepository()

    set_resource_repository(resource_repo)
    set_storage_client(InMemoryStorageClient())
    set_inference_client(MockInferenceClient())
    set_vacant_property_repository(vacant_repo)
    set_admin_user_repository(admin_repo)
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


class TestAdminListResources:
    async def test_returns_resources_within_bounds(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        inside = _make_resource(lat=35.0, lng=139.0)
        outside = _make_resource(lat=40.0, lng=145.0)
        resource_repo.insert(inside)
        resource_repo.insert(outside)

        token = await _login(client)
        res = client.get(
            "/admin/resources",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "min_latitude": 34.0,
                "min_longitude": 138.0,
                "max_latitude": 36.0,
                "max_longitude": 140.0,
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert len(body["resources"]) == 1
        assert body["resources"][0]["resource_id"] == str(inside.resource_id)

    def test_requires_authentication(self, client: TestClient) -> None:
        res = client.get(
            "/admin/resources",
            params={
                "min_latitude": 34.0,
                "min_longitude": 138.0,
                "max_latitude": 36.0,
                "max_longitude": 140.0,
            },
        )
        assert res.status_code == 401


class TestAdminUpdateResource:
    async def test_updates_resource_fields(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        resource = _make_resource()
        resource_repo.insert(resource)
        token = await _login(client)

        res = client.patch(
            f"/admin/resources/{resource.resource_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "更新後の名称", "municipality": "渋谷区"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "更新後の名称"
        assert body["municipality"] == "渋谷区"

    async def test_returns_404_for_unknown_resource(self, client: TestClient) -> None:
        token = await _login(client)
        res = client.patch(
            f"/admin/resources/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "更新後の名称"},
        )
        assert res.status_code == 404

    async def test_rejects_partial_latlng(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        resource = _make_resource()
        resource_repo.insert(resource)
        token = await _login(client)

        res = client.patch(
            f"/admin/resources/{resource.resource_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"latitude": 36.0},
        )
        assert res.status_code == 400


class TestAdminDeleteResource:
    async def test_deletes_resource(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        resource = _make_resource()
        resource_repo.insert(resource)
        token = await _login(client)

        res = client.delete(
            f"/admin/resources/{resource.resource_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 204
        assert len(resource_repo) == 0

    async def test_returns_404_for_unknown_resource(self, client: TestClient) -> None:
        token = await _login(client)
        res = client.delete(
            f"/admin/resources/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404

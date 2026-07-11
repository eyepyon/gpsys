"""更新依頼API（/update-requests, /admin/update-requests/*）の結合テスト。"""

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
    set_update_request_repository,
    set_vacant_property_repository,
)
from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.update_request import InMemoryUpdateRequestRepository
from regional_revitalization.vacant_property import InMemoryVacantPropertyRepository


def _make_resource() -> RegionalResource:
    now = datetime.now()
    return RegionalResource(
        resource_id=uuid4(),
        name="既存の資源",
        category="施設",
        description="既存の説明文",
        location=GeoPoint(latitude=35.68, longitude=139.76),
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
    set_update_request_repository(InMemoryUpdateRequestRepository())
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


class TestSubmitUpdateRequest:
    def test_anyone_can_submit_without_authentication(self, client: TestClient) -> None:
        res = client.post(
            "/update-requests",
            json={
                "target_resource_id": None,
                "requester_contact": "test@example.com",
                "requested_changes": {
                    "name": "新規資源",
                    "category": "施設",
                    "description": "説明",
                    "latitude": 35.0,
                    "longitude": 139.0,
                },
                "message": "追加してください",
            },
        )
        assert res.status_code == 201
        assert res.json()["status"] == "pending"

    def test_rejects_empty_changes(self, client: TestClient) -> None:
        res = client.post(
            "/update-requests",
            json={"target_resource_id": None, "requested_changes": {}},
        )
        assert res.status_code == 400


class TestAdminListUpdateRequests:
    async def test_requires_authentication(self, client: TestClient) -> None:
        res = client.get("/admin/update-requests")
        assert res.status_code == 401

    async def test_lists_pending_requests(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        client.post(
            "/update-requests",
            json={
                "target_resource_id": None,
                "requested_changes": {
                    "name": "新規資源",
                    "category": "施設",
                    "description": "説明",
                    "latitude": 35.0,
                    "longitude": 139.0,
                },
            },
        )
        token = await _login(client)
        res = client.get(
            "/admin/update-requests",
            headers={"Authorization": f"Bearer {token}"},
            params={"status": "pending"},
        )
        assert res.status_code == 200
        assert len(res.json()["requests"]) == 1


class TestAdminApproveRequest:
    async def test_approves_existing_resource_update(
        self, client: TestClient, resource_repo: InMemoryResourceRepository
    ) -> None:
        resource = _make_resource()
        resource_repo.insert(resource)

        submit_res = client.post(
            "/update-requests",
            json={
                "target_resource_id": str(resource.resource_id),
                "requested_changes": {"name": "承認後の名称"},
            },
        )
        request_id = submit_res.json()["request_id"]

        token = await _login(client)
        approve_res = client.post(
            f"/admin/update-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["name"] == "承認後の名称"

    async def test_returns_404_for_unknown_request(self, client: TestClient) -> None:
        token = await _login(client)
        res = client.post(
            f"/admin/update-requests/{uuid4()}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404


class TestAdminRejectRequest:
    async def test_rejects_pending_request(self, client: TestClient) -> None:
        submit_res = client.post(
            "/update-requests",
            json={
                "target_resource_id": None,
                "requested_changes": {
                    "name": "新規資源",
                    "category": "施設",
                    "description": "説明",
                    "latitude": 35.0,
                    "longitude": 139.0,
                },
            },
        )
        request_id = submit_res.json()["request_id"]

        token = await _login(client)
        res = client.post(
            f"/admin/update-requests/{request_id}/reject",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"

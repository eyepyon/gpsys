"""管理画面向けAPIエンドポイント（/admin/*）の結合テスト。

`fastapi.testclient.TestClient`を用いて、ログイン・ログアウト・
管理ユーザーCRUD・ダッシュボード・統計情報エンドポイントの正常系・異常系を検証する。
"""

from __future__ import annotations

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
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.vacant_property import InMemoryVacantPropertyRepository


@pytest.fixture(autouse=True)
def _reset_shared_instances() -> None:
    from regional_revitalization.inference import MockInferenceClient

    resource_repo = InMemoryResourceRepository()
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


async def _create_user_and_login(client: TestClient, username: str = "alice") -> str:
    """テスト用の管理ユーザーを作成し、ログインしてセッショントークンを返す。"""
    from regional_revitalization.api import get_admin_user_repository

    repo = get_admin_user_repository()
    await create_admin_user(repo, username, "password123", "Alice")

    res = client.post(
        "/admin/auth/login", json={"username": username, "password": "password123"}
    )
    assert res.status_code == 200
    return res.json()["session_token"]


class TestAdminLogin:
    @pytest.mark.anyio
    async def test_login_succeeds_with_correct_credentials(
        self, client: TestClient
    ) -> None:
        token = await _create_user_and_login(client)
        assert len(token) > 0

    def test_login_fails_with_wrong_password(self, client: TestClient) -> None:
        res = client.post(
            "/admin/auth/login", json={"username": "nobody", "password": "wrong"}
        )
        assert res.status_code == 401


class TestAdminAuthenticatedEndpoints:
    @pytest.mark.anyio
    async def test_me_requires_authentication(self, client: TestClient) -> None:
        res = client.get("/admin/auth/me")
        assert res.status_code == 401

    @pytest.mark.anyio
    async def test_me_returns_current_user(self, client: TestClient) -> None:
        token = await _create_user_and_login(client)
        res = client.get(
            "/admin/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert res.json()["username"] == "alice"

    @pytest.mark.anyio
    async def test_logout_invalidates_session(self, client: TestClient) -> None:
        token = await _create_user_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        logout_res = client.post("/admin/auth/logout", headers=headers)
        assert logout_res.status_code == 204

        me_res = client.get("/admin/auth/me", headers=headers)
        assert me_res.status_code == 401

    @pytest.mark.anyio
    async def test_dashboard_returns_counts(self, client: TestClient) -> None:
        token = await _create_user_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        res = client.get("/admin/dashboard", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["admin_user_count"] == 1
        assert body["regional_resource_count"] == 0


class TestAdminUserManagement:
    @pytest.mark.anyio
    async def test_create_list_update_delete_user_flow(
        self, client: TestClient
    ) -> None:
        token = await _create_user_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_res = client.post(
            "/admin/users",
            headers=headers,
            json={
                "username": "bob",
                "password": "password456",
                "display_name": "Bob",
            },
        )
        assert create_res.status_code == 201
        bob_id = create_res.json()["admin_user_id"]

        list_res = client.get("/admin/users", headers=headers)
        assert list_res.status_code == 200
        usernames = {u["username"] for u in list_res.json()}
        assert usernames == {"alice", "bob"}

        update_res = client.patch(
            f"/admin/users/{bob_id}", headers=headers, json={"is_active": False}
        )
        assert update_res.status_code == 200
        assert update_res.json()["is_active"] is False

        delete_res = client.delete(f"/admin/users/{bob_id}", headers=headers)
        assert delete_res.status_code == 204

        list_res_after = client.get("/admin/users", headers=headers)
        usernames_after = {u["username"] for u in list_res_after.json()}
        assert usernames_after == {"alice"}

    @pytest.mark.anyio
    async def test_cannot_delete_self(self, client: TestClient) -> None:
        token = await _create_user_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_res = client.get("/admin/auth/me", headers=headers)
        self_id = me_res.json()["admin_user_id"]

        delete_res = client.delete(f"/admin/users/{self_id}", headers=headers)
        assert delete_res.status_code == 400

    @pytest.mark.anyio
    async def test_create_user_rejects_short_password(
        self, client: TestClient
    ) -> None:
        token = await _create_user_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        res = client.post(
            "/admin/users",
            headers=headers,
            json={"username": "carol", "password": "short", "display_name": "Carol"},
        )
        assert res.status_code == 400

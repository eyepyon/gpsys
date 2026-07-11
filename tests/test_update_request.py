"""更新依頼（申請・承認フロー）モジュール（update_request.py）の単体テスト。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.update_request import (
    InMemoryUpdateRequestRepository,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    approve_request,
    reject_request,
    submit_update_request,
)


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


class TestSubmitUpdateRequest:
    def test_creates_pending_request_for_existing_resource(self) -> None:
        resource_id = uuid4()
        request = submit_update_request(
            resource_id, "contact@example.com", {"name": "新名称"}, "誤字修正"
        )
        assert request.status == STATUS_PENDING
        assert request.target_resource_id == resource_id
        assert request.requested_changes == {"name": "新名称"}

    def test_rejects_empty_changes(self) -> None:
        with pytest.raises(ValueError, match="requested_changesは空"):
            submit_update_request(uuid4(), None, {}, None)

    def test_new_registration_proposal_requires_all_fields(self) -> None:
        with pytest.raises(ValueError, match="新規登録提案"):
            submit_update_request(None, None, {"name": "新規資源"}, None)

    def test_new_registration_proposal_succeeds_with_all_fields(self) -> None:
        request = submit_update_request(
            None,
            None,
            {
                "name": "新規資源",
                "category": "施設",
                "description": "説明",
                "latitude": 35.0,
                "longitude": 139.0,
            },
            None,
        )
        assert request.target_resource_id is None
        assert request.status == STATUS_PENDING


class TestApproveRequest:
    async def test_approves_and_updates_existing_resource(self) -> None:
        resource = _make_resource()
        resource_repo = InMemoryResourceRepository([resource])
        request_repo = InMemoryUpdateRequestRepository()
        storage = InMemoryStorageClient()
        admin_id = uuid4()

        request = submit_update_request(
            resource.resource_id, None, {"name": "更新後の名称"}, None
        )
        await request_repo.insert(request)

        result = await approve_request(
            request_repo, resource_repo, storage, request.request_id, admin_id
        )
        assert result.name == "更新後の名称"

        updated_request = await request_repo.get_by_id(request.request_id)
        assert updated_request.status == STATUS_APPROVED
        assert updated_request.reviewed_by_admin_id == admin_id

    async def test_approves_new_registration_proposal(self) -> None:
        resource_repo = InMemoryResourceRepository()
        request_repo = InMemoryUpdateRequestRepository()
        storage = InMemoryStorageClient()
        admin_id = uuid4()

        request = submit_update_request(
            None,
            None,
            {
                "name": "新規資源",
                "category": "施設",
                "description": "説明",
                "latitude": 35.0,
                "longitude": 139.0,
            },
            None,
        )
        await request_repo.insert(request)

        result = await approve_request(
            request_repo, resource_repo, storage, request.request_id, admin_id
        )
        assert result.name == "新規資源"
        assert len(resource_repo) == 1

    async def test_raises_for_unknown_request(self) -> None:
        resource_repo = InMemoryResourceRepository()
        request_repo = InMemoryUpdateRequestRepository()
        storage = InMemoryStorageClient()
        with pytest.raises(ValueError, match="見つかりません"):
            await approve_request(
                request_repo, resource_repo, storage, uuid4(), uuid4()
            )

    async def test_raises_if_already_processed(self) -> None:
        resource = _make_resource()
        resource_repo = InMemoryResourceRepository([resource])
        request_repo = InMemoryUpdateRequestRepository()
        storage = InMemoryStorageClient()
        admin_id = uuid4()

        request = submit_update_request(
            resource.resource_id, None, {"name": "更新後の名称"}, None
        )
        await request_repo.insert(request)
        await approve_request(
            request_repo, resource_repo, storage, request.request_id, admin_id
        )

        with pytest.raises(ValueError, match="既に処理済み"):
            await approve_request(
                request_repo, resource_repo, storage, request.request_id, admin_id
            )

    async def test_raises_if_target_resource_missing(self) -> None:
        resource_repo = InMemoryResourceRepository()
        request_repo = InMemoryUpdateRequestRepository()
        storage = InMemoryStorageClient()
        admin_id = uuid4()

        request = submit_update_request(
            uuid4(), None, {"name": "更新後の名称"}, None
        )
        await request_repo.insert(request)

        with pytest.raises(ValueError, match="対象の地域資源が見つかりません"):
            await approve_request(
                request_repo, resource_repo, storage, request.request_id, admin_id
            )


class TestRejectRequest:
    async def test_rejects_pending_request(self) -> None:
        request_repo = InMemoryUpdateRequestRepository()
        admin_id = uuid4()
        request = submit_update_request(uuid4(), None, {"name": "x"}, None)
        await request_repo.insert(request)

        await reject_request(request_repo, request.request_id, admin_id)

        updated = await request_repo.get_by_id(request.request_id)
        assert updated.status == STATUS_REJECTED
        assert updated.reviewed_by_admin_id == admin_id

    async def test_raises_for_unknown_request(self) -> None:
        request_repo = InMemoryUpdateRequestRepository()
        with pytest.raises(ValueError, match="見つかりません"):
            await reject_request(request_repo, uuid4(), uuid4())

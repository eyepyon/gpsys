"""利用者からの地域資源データ更新依頼（申請・承認フロー）モジュール。

`migrations/002_admin_schema.sql`の`resource_update_requests`テーブルに対応する。
利用者は会員登録機能を持たないため、依頼者情報は自由記述の連絡先文字列
（`requester_contact`）として保持する。

申請内容（`requested_changes`）は、既存の地域資源に対する変更提案の場合は
`target_resource_id`を指定し、まだ存在しない資源の新規登録提案の場合は
`target_resource_id`をNoneとする。いずれの場合も、承認（`approve_request()`）
時に初めて`regional_resources`テーブルへの実際の反映（UPDATE/INSERT）が行われる。
却下（`reject_request()`）した申請は反映されない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.registration import register_resource
from regional_revitalization.repository import ResourceRepository
from regional_revitalization.storage import StorageClient

# 依頼のライフサイクルを表すステータス値。
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

_VALID_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED}

# requested_changesに許可するキー。予期しないキーの混入を防ぐため
# ホワイトリスト方式で検証する。
_ALLOWED_CHANGE_KEYS = {
    "name",
    "category",
    "description",
    "latitude",
    "longitude",
    "municipality",
}


@dataclass(frozen=True)
class UpdateRequest:
    """地域資源データの更新依頼1件。

    Attributes:
        request_id: 一意識別子。
        target_resource_id: 変更提案の対象となる既存資源のID。新規登録提案の
            場合はNone。
        requester_contact: 依頼者の連絡先（自由記述、任意）。
        requested_changes: 提案する変更内容。キーは`name`/`category`/
            `description`/`latitude`/`longitude`/`municipality`のいずれか
            のみを許可する。新規登録提案の場合は`name`/`category`/
            `description`/`latitude`/`longitude`が必須。
        message: 依頼理由・補足メッセージ（任意）。
        status: `pending`/`approved`/`rejected`のいずれか。
        reviewed_by_admin_id: 承認・却下を行った管理ユーザーのID。
            未対応の間はNone。
        reviewed_at: 承認・却下が行われた時刻。未対応の間はNone。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    request_id: UUID
    target_resource_id: UUID | None
    requester_contact: str | None
    requested_changes: dict[str, object]
    message: str | None
    status: str
    reviewed_by_admin_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"statusは{_VALID_STATUSES}のいずれかである必要があります: {self.status}"
            )
        invalid_keys = set(self.requested_changes.keys()) - _ALLOWED_CHANGE_KEYS
        if invalid_keys:
            raise ValueError(
                f"requested_changesに許可されていないキーがあります: {invalid_keys}"
            )


class UpdateRequestRepository(Protocol):
    """更新依頼の永続化リポジトリ（Cloud SQLをバックエンドとする）。"""

    async def insert(self, request: UpdateRequest) -> UUID:
        """更新依頼を登録し、`request_id`を返す。"""
        ...

    async def get_by_id(self, request_id: UUID) -> UpdateRequest | None:
        """`request_id`に一致する更新依頼を返す。存在しない場合はNoneを返す。"""
        ...

    async def list_by_status(self, status: str | None) -> list[UpdateRequest]:
        """`status`で絞り込んだ更新依頼一覧を作成日時の降順で返す。

        `status`がNoneの場合は全件を返す。
        """
        ...

    async def update_status(
        self,
        request_id: UUID,
        status: str,
        reviewed_by_admin_id: UUID,
        reviewed_at: datetime,
    ) -> None:
        """更新依頼のステータス・審査情報を更新する。"""
        ...


class InMemoryUpdateRequestRepository:
    """テスト・ローカル開発用のインメモリ`UpdateRequestRepository`実装。"""

    def __init__(self) -> None:
        self._requests_by_id: dict[UUID, UpdateRequest] = {}

    async def insert(self, request: UpdateRequest) -> UUID:
        self._requests_by_id[request.request_id] = request
        return request.request_id

    async def get_by_id(self, request_id: UUID) -> UpdateRequest | None:
        return self._requests_by_id.get(request_id)

    async def list_by_status(self, status: str | None) -> list[UpdateRequest]:
        requests = list(self._requests_by_id.values())
        if status is not None:
            requests = [r for r in requests if r.status == status]
        return sorted(requests, key=lambda r: r.created_at, reverse=True)

    async def update_status(
        self,
        request_id: UUID,
        status: str,
        reviewed_by_admin_id: UUID,
        reviewed_at: datetime,
    ) -> None:
        existing = self._requests_by_id.get(request_id)
        if existing is None:
            raise ValueError(f"更新依頼が見つかりません: {request_id}")
        self._requests_by_id[request_id] = UpdateRequest(
            request_id=existing.request_id,
            target_resource_id=existing.target_resource_id,
            requester_contact=existing.requester_contact,
            requested_changes=existing.requested_changes,
            message=existing.message,
            status=status,
            reviewed_by_admin_id=reviewed_by_admin_id,
            reviewed_at=reviewed_at,
            created_at=existing.created_at,
            updated_at=reviewed_at,
        )

    def __len__(self) -> int:
        return len(self._requests_by_id)


def submit_update_request(
    target_resource_id: UUID | None,
    requester_contact: str | None,
    requested_changes: dict[str, object],
    message: str | None,
) -> UpdateRequest:
    """利用者からの更新依頼を新規作成する（永続化は呼び出し側の責務）。

    Args:
        target_resource_id: 変更提案の対象資源ID。新規登録提案の場合はNone。
        requester_contact: 依頼者の連絡先（任意）。
        requested_changes: 提案する変更内容。空の辞書は不可。
        message: 依頼理由・補足メッセージ（任意）。

    Returns:
        作成された`UpdateRequest`（`status="pending"`）。

    Raises:
        ValueError: `requested_changes`が空、許可されていないキーを含む、
            または新規登録提案（`target_resource_id is None`）で
            `name`/`category`/`description`/`latitude`/`longitude`が
            揃っていない場合。
    """
    if not requested_changes:
        raise ValueError("requested_changesは空であってはなりません")

    if target_resource_id is None:
        required_keys = {"name", "category", "description", "latitude", "longitude"}
        missing = required_keys - set(requested_changes.keys())
        if missing:
            raise ValueError(
                f"新規登録提案には{required_keys}が全て必要です。不足: {missing}"
            )

    now = datetime.now(timezone.utc)
    return UpdateRequest(
        request_id=uuid4(),
        target_resource_id=target_resource_id,
        requester_contact=requester_contact,
        requested_changes=requested_changes,
        message=message,
        status=STATUS_PENDING,
        reviewed_by_admin_id=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )


async def approve_request(
    update_request_repository: UpdateRequestRepository,
    resource_repository: ResourceRepository,
    storage_client: StorageClient,
    request_id: UUID,
    admin_user_id: UUID,
) -> RegionalResource:
    """更新依頼を承認し、`regional_resources`テーブルに変更を反映する。

    `target_resource_id`が指定されている場合は既存資源をUPDATEし、
    Noneの場合は新規登録（INSERT、`register_resource()`経由）する。

    Args:
        update_request_repository: 更新依頼の永続化リポジトリ。
        resource_repository: 反映先の地域資源リポジトリ。
        storage_client: 新規登録提案の場合に使用するストレージクライアント
            （添付ファイルは更新依頼では扱わないため、実質未使用だが
            `register_resource()`のシグネチャに合わせて受け取る）。
        request_id: 承認対象の更新依頼ID。
        admin_user_id: 承認操作を行った管理ユーザーのID。

    Returns:
        反映後の`RegionalResource`。

    Raises:
        ValueError: 更新依頼が存在しない、既に`pending`以外の状態、
            または対象資源が存在しない場合。
    """
    request = await update_request_repository.get_by_id(request_id)
    if request is None:
        raise ValueError(f"更新依頼が見つかりません: {request_id}")
    if request.status != STATUS_PENDING:
        raise ValueError(
            f"この更新依頼は既に処理済みです（status={request.status}）"
        )

    changes = request.requested_changes

    if request.target_resource_id is not None:
        existing = resource_repository.get_by_id(request.target_resource_id)
        if existing is None:
            raise ValueError(
                f"対象の地域資源が見つかりません: {request.target_resource_id}"
            )
        latitude = changes.get("latitude")
        longitude = changes.get("longitude")
        location = (
            GeoPoint(latitude=float(latitude), longitude=float(longitude))
            if latitude is not None and longitude is not None
            else None
        )
        resource_repository.update(
            request.target_resource_id,
            changes.get("name"),
            changes.get("category"),
            changes.get("description"),
            location,
            changes.get("municipality"),
        )
        result = resource_repository.get_by_id(request.target_resource_id)
        assert result is not None
    else:
        location = GeoPoint(
            latitude=float(changes["latitude"]), longitude=float(changes["longitude"])
        )
        result = register_resource(
            resource_repository,
            storage_client,
            str(changes["name"]),
            str(changes["category"]),
            str(changes["description"]),
            location,
            None,
            None,
        )

    now = datetime.now(timezone.utc)
    await update_request_repository.update_status(
        request_id, STATUS_APPROVED, admin_user_id, now
    )
    return result


async def reject_request(
    update_request_repository: UpdateRequestRepository,
    request_id: UUID,
    admin_user_id: UUID,
) -> None:
    """更新依頼を却下する（`regional_resources`への反映は行わない）。

    Raises:
        ValueError: 更新依頼が存在しない、または既に`pending`以外の状態の場合。
    """
    request = await update_request_repository.get_by_id(request_id)
    if request is None:
        raise ValueError(f"更新依頼が見つかりません: {request_id}")
    if request.status != STATUS_PENDING:
        raise ValueError(
            f"この更新依頼は既に処理済みです（status={request.status}）"
        )

    now = datetime.now(timezone.utc)
    await update_request_repository.update_status(
        request_id, STATUS_REJECTED, admin_user_id, now
    )

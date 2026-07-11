"""利用者の居抜き物件検索リクエスト履歴の記録モジュール。

`POST /vacant-properties/search`が呼び出される度に、検索した場所・条件・
表示できた件数を`SearchRequestRepository`経由で記録する。管理画面は、この
履歴一覧から「この場所でGoogle Places APIをリアルタイム検索する」操作を
トリガーできる（`places_search.py`参照）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from regional_revitalization.models import GeoPoint
from regional_revitalization.vacant_property import BusinessStatus


@dataclass(frozen=True)
class SearchRequest:
    """利用者の検索リクエスト履歴1件。

    Attributes:
        search_request_id: 一意識別子。
        location: 検索基準となった位置情報。
        radius_km: 検索半径（キロメートル）。
        business_status: 検索時に指定された営業状態（絞り込みが無い呼び出し
            経路のために将来的にNoneも許容するが、現状のAPIでは必須項目）。
        types: 検索時に指定された業種タグ（絞り込み無しの場合はNone）。
        result_count: 検索によって実際に返された件数。
        created_at: 記録日時。
    """

    search_request_id: UUID
    location: GeoPoint
    radius_km: float
    business_status: BusinessStatus | None
    types: list[str] | None
    result_count: int
    created_at: datetime


class SearchRequestRepository(Protocol):
    """検索リクエスト履歴の永続化リポジトリ（Cloud SQLをバックエンドとする）。"""

    async def insert(self, request: SearchRequest) -> UUID:
        """検索リクエスト履歴を1件記録し、`search_request_id`を返す。"""
        ...

    async def list_recent(self, limit: int) -> list[SearchRequest]:
        """直近の検索リクエスト履歴を作成日時の降順で最大`limit`件返す。"""
        ...

    async def get_by_id(self, search_request_id: UUID) -> SearchRequest | None:
        """`search_request_id`に一致する検索リクエスト履歴を返す。"""
        ...


class InMemorySearchRequestRepository:
    """テスト・ローカル開発用のインメモリ`SearchRequestRepository`実装。"""

    def __init__(self) -> None:
        self._requests_by_id: dict[UUID, SearchRequest] = {}

    async def insert(self, request: SearchRequest) -> UUID:
        self._requests_by_id[request.search_request_id] = request
        return request.search_request_id

    async def list_recent(self, limit: int) -> list[SearchRequest]:
        requests = sorted(
            self._requests_by_id.values(), key=lambda r: r.created_at, reverse=True
        )
        return requests[:limit]

    async def get_by_id(self, search_request_id: UUID) -> SearchRequest | None:
        return self._requests_by_id.get(search_request_id)

    def __len__(self) -> int:
        return len(self._requests_by_id)


async def record_search_request(
    repository: SearchRequestRepository,
    location: GeoPoint,
    radius_km: float,
    business_status: BusinessStatus | None,
    types: list[str] | None,
    result_count: int,
) -> SearchRequest:
    """利用者の検索リクエストを1件記録する。

    Args:
        repository: 記録先のリポジトリ。
        location: 検索基準となった位置情報。
        radius_km: 検索半径（キロメートル）。
        business_status: 検索時に指定された営業状態。
        types: 検索時に指定された業種タグ。
        result_count: 検索によって実際に返された件数。

    Returns:
        記録された`SearchRequest`。
    """
    request = SearchRequest(
        search_request_id=uuid4(),
        location=location,
        radius_km=radius_km,
        business_status=business_status,
        types=types,
        result_count=result_count,
        created_at=datetime.now(timezone.utc),
    )
    await repository.insert(request)
    return request

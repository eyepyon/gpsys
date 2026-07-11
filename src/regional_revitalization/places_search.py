"""管理画面向けGoogle Places APIリアルタイム検索モジュール。

管理者が管理画面から「この場所でGoogle Places APIを検索する」を実行した際の
ロジックを実装する。既存の`vacant_property_sync_job.py`（`RealPlacesApiClient`,
Place Details API、`place_id`指定の詳細取得）とは異なり、本モジュールは
Places API Text Search（キーワード・位置・半径による検索、`place_id`が
未知の新規スポットを発見するための機能）を扱う。

**設計方針（コスト・品質管理）**: 検索結果は`PlacesSearchResultRepository`に
「登録待ち」の状態で一時保存するだけで、`vacant_property_candidates`への
反映は行わない。管理者が個別に確認し、`register_search_result()`を明示的に
呼び出した結果のみが実際のデータとして登録される。これにより、Places API
呼び出しの発生源（利用者の検索行動ではなく管理者の明示的な操作のみ）と、
登録データの品質を管理者が完全に制御できる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from regional_revitalization.models import GeoPoint
from regional_revitalization.vacant_property import (
    BusinessStatus,
    PlaceDetailsResult,
    PlacesApiError,
    VacantPropertyCandidate,
    VacantPropertyRepository,
    estimate_closure_period,
)


@dataclass(frozen=True)
class PlacesSearchResult:
    """Places APIリアルタイム検索で発見した1件（登録待ちの状態）。

    Attributes:
        result_id: 一意識別子。
        search_request_id: 起点となった利用者検索履歴のID
            （管理者が任意の場所を直接指定して検索した場合はNone）。
        place_id: Google Places APIのPlace ID。
        name: スポット名。
        location: 位置情報。
        business_status: Places APIの営業状態。
        types: 業種・ジャンルタグ配列。
        address: 住所。取得できない場合はNone。
        phone_number: 電話番号。取得できない場合はNone。
        is_registered: 管理者が`register_search_result()`で
            `vacant_property_candidates`へ反映済みかどうか。
        created_at: 検索実行日時。
    """

    result_id: UUID
    search_request_id: UUID | None
    place_id: str
    name: str
    location: GeoPoint
    business_status: BusinessStatus
    types: list[str]
    address: str | None
    phone_number: str | None
    is_registered: bool
    created_at: datetime


class PlacesSearchClient(Protocol):
    """Google Places API（Text Search）を呼び出すクライアント。"""

    def search_text(
        self, location: GeoPoint, radius_km: float, keyword: str | None
    ) -> list[PlaceDetailsResult]:
        """指定した位置・半径・キーワードでPlaces APIのテキスト検索を実行する。

        レート制限・APIキー無効時は`PlacesApiError`を発生させる。
        """
        ...


class MockPlacesSearchClient:
    """テスト用の`PlacesSearchClient`実装。固定のレスポンスを返す。"""

    def __init__(
        self, results: list[PlaceDetailsResult] | None = None, should_error: bool = False
    ) -> None:
        self._results = results if results is not None else []
        self._should_error = should_error

    def search_text(
        self, location: GeoPoint, radius_km: float, keyword: str | None
    ) -> list[PlaceDetailsResult]:
        if self._should_error:
            raise PlacesApiError("Places API検索呼び出しに失敗しました")
        return self._results


class PlacesSearchResultRepository(Protocol):
    """Places APIリアルタイム検索結果（登録待ち）の永続化リポジトリ。"""

    async def insert_many(self, results: list[PlacesSearchResult]) -> None:
        """検索結果をまとめて保存する。"""
        ...

    async def get_by_id(self, result_id: UUID) -> PlacesSearchResult | None:
        """`result_id`に一致する検索結果を返す。"""
        ...

    async def list_by_search_request(
        self, search_request_id: UUID | None
    ) -> list[PlacesSearchResult]:
        """`search_request_id`に紐づく検索結果一覧を返す（Noneの場合は全件）。"""
        ...

    async def mark_registered(self, result_id: UUID) -> None:
        """指定した検索結果を`is_registered=true`にする。"""
        ...


class InMemoryPlacesSearchResultRepository:
    """テスト・ローカル開発用のインメモリ`PlacesSearchResultRepository`実装。"""

    def __init__(self) -> None:
        self._results_by_id: dict[UUID, PlacesSearchResult] = {}

    async def insert_many(self, results: list[PlacesSearchResult]) -> None:
        for result in results:
            self._results_by_id[result.result_id] = result

    async def get_by_id(self, result_id: UUID) -> PlacesSearchResult | None:
        return self._results_by_id.get(result_id)

    async def list_by_search_request(
        self, search_request_id: UUID | None
    ) -> list[PlacesSearchResult]:
        results = list(self._results_by_id.values())
        if search_request_id is not None:
            results = [
                r for r in results if r.search_request_id == search_request_id
            ]
        return sorted(results, key=lambda r: r.created_at, reverse=True)

    async def mark_registered(self, result_id: UUID) -> None:
        existing = self._results_by_id.get(result_id)
        if existing is None:
            raise ValueError(f"検索結果が見つかりません: {result_id}")
        self._results_by_id[result_id] = PlacesSearchResult(
            result_id=existing.result_id,
            search_request_id=existing.search_request_id,
            place_id=existing.place_id,
            name=existing.name,
            location=existing.location,
            business_status=existing.business_status,
            types=existing.types,
            address=existing.address,
            phone_number=existing.phone_number,
            is_registered=True,
            created_at=existing.created_at,
        )

    def __len__(self) -> int:
        return len(self._results_by_id)


async def execute_places_search(
    places_search_client: PlacesSearchClient,
    places_search_result_repository: PlacesSearchResultRepository,
    location: GeoPoint,
    radius_km: float,
    keyword: str | None,
    search_request_id: UUID | None,
) -> list[PlacesSearchResult]:
    """指定した場所でGoogle Places APIのリアルタイム検索を実行し、

    結果を「登録待ち」の状態で保存する。

    Args:
        places_search_client: Places API検索を呼び出すクライアント。
        places_search_result_repository: 検索結果の保存先リポジトリ。
        location: 検索基準となる位置情報。
        radius_km: 検索半径（キロメートル）。正の数であること。
        keyword: 検索キーワード（業種名等、任意）。
        search_request_id: 起点となった利用者検索履歴のID（任意）。

    Returns:
        保存された`PlacesSearchResult`のリスト。

    Raises:
        ValueError: `radius_km`が0以下の場合。
        PlacesApiError: Places API呼び出しが失敗した場合。
    """
    if radius_km <= 0:
        raise ValueError(f"radius_kmは正の数である必要があります: {radius_km}")

    details_list = places_search_client.search_text(location, radius_km, keyword)

    now = datetime.now(timezone.utc)
    results = [
        PlacesSearchResult(
            result_id=uuid4(),
            search_request_id=search_request_id,
            place_id=details.place_id,
            name=details.name,
            location=details.location,
            business_status=details.business_status,
            types=details.types,
            address=details.address,
            phone_number=details.phone_number,
            is_registered=False,
            created_at=now,
        )
        for details in details_list
    ]
    await places_search_result_repository.insert_many(results)
    return results


async def register_search_result(
    places_search_result_repository: PlacesSearchResultRepository,
    vacant_property_repository: VacantPropertyRepository,
    result_id: UUID,
) -> VacantPropertyCandidate:
    """管理者が確認したPlaces API検索結果を、居抜き物件候補として

    `vacant_property_candidates`にUPSERTする。

    Args:
        places_search_result_repository: 検索結果の保存先リポジトリ。
        vacant_property_repository: 反映先の居抜き物件候補リポジトリ。
        result_id: 登録対象の検索結果ID。

    Returns:
        登録された`VacantPropertyCandidate`。

    Raises:
        ValueError: `result_id`が存在しない、または既に登録済みの場合。
    """
    result = await places_search_result_repository.get_by_id(result_id)
    if result is None:
        raise ValueError(f"検索結果が見つかりません: {result_id}")
    if result.is_registered:
        raise ValueError("この検索結果は既に登録済みです")

    # VacantPropertyCandidate.data_fetched_atはnaive datetime（datetime.now()）
    # との比較を前提としているため、awareなdatetime.now(timezone.utc)ではなく
    # naiveなdatetime.now()を使用する（vacant_property.py既存実装との一貫性）。
    now = datetime.now()
    start, end = estimate_closure_period(data_fetched_at=now, last_review_time=None)
    candidate = VacantPropertyCandidate(
        place_id=result.place_id,
        name=result.name,
        location=result.location,
        business_status=result.business_status,
        types=result.types,
        address=result.address,
        phone_number=result.phone_number,
        data_fetched_at=now,
        last_review_time=None,
        estimated_closure_period_start=start,
        estimated_closure_period_end=end,
    )
    vacant_property_repository.upsert_by_place_id(candidate)
    await places_search_result_repository.mark_registered(result_id)
    return candidate

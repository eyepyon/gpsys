"""居抜き物件（VacantPropertyCandidate）関連のデータモデルとリポジトリ実装。

`design.md`の「コンポーネント5: 居抜き物件同期サービス
(VacantPropertySyncService)」に定義された`BusinessStatus`, `VacantPropertyCandidate`,
`PlaceDetailsResult`, `SyncResult`のデータクラス、および
`VacantPropertyRepository` Protocolとテスト用インメモリ実装
`InMemoryVacantPropertyRepository`を実装する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from regional_revitalization.models import GeoPoint
from regional_revitalization.repository import haversine_distance_km


class BusinessStatus(str, Enum):
    """Places APIの`business_status`フィールド。

    Attributes:
        OPERATIONAL: 営業中。
        CLOSED_TEMPORARILY: 一時休業。
        CLOSED_PERMANENTLY: 完全閉店・廃業。
    """

    OPERATIONAL = "OPERATIONAL"
    CLOSED_TEMPORARILY = "CLOSED_TEMPORARILY"
    CLOSED_PERMANENTLY = "CLOSED_PERMANENTLY"


@dataclass(frozen=True)
class VacantPropertyCandidate:
    """居抜き物件候補（閉店・廃業が検知されたスポット）

    Attributes:
        place_id: Google Places APIのPlace ID。一意識別子。
            重複防止・再取得時の同一性判定に使用する（空文字列は不可）。
        name: 旧店舗名（空文字列は不可）。
        location: スポットの位置情報（有効な`GeoPoint`であること）。
        business_status: Places APIの営業状態。
        types: 業種・ジャンルタグ配列（例: `["restaurant", "cafe"]`）。
            該当タグが無い場合は空リスト`[]`とする（Noneは不可）。
        address: 住所。取得できない場合はNone。
        phone_number: 電話番号。取得できない場合はNone。
        data_fetched_at: このレコードのデータをGoogleから取得した時刻。
            未来の時刻であってはならない。
        last_review_time: 取得できた最新レビューの投稿時刻。
            レビューが存在しない場合はNone。
        estimated_closure_period_start: 推定廃業時期レンジの開始。
        estimated_closure_period_end: 推定廃業時期レンジの終了。

    Raises:
        ValueError: 検証ルール（`design.md`モデル4）のいずれかに違反する場合。
    """

    place_id: str
    name: str
    location: GeoPoint
    business_status: BusinessStatus
    types: list[str]
    address: str | None
    phone_number: str | None
    data_fetched_at: datetime
    last_review_time: datetime | None
    estimated_closure_period_start: datetime | None
    estimated_closure_period_end: datetime | None
    # 以下はGoogle Places APIからは取得できない、管理画面での手動編集専用の
    # 項目（Requirements: 管理画面のデータ編集メニュー）。フロント（利用者向け
    # 画面）には表示しない。未入力の場合はいずれもNone。
    rent_yen: int | None = None
    area_sqm: float | None = None
    built_year: int | None = None
    structure: str | None = None

    def __post_init__(self) -> None:
        """`design.md`モデル4の検証ルールを検証する。

        違反時は`ValueError`を発生させる（Requirements 13.2, 13.3, 14.4）。
        """
        if self.place_id == "":
            raise ValueError("place_idは空文字列であってはなりません")
        if self.name == "":
            raise ValueError("nameは空文字列であってはなりません")
        if self.types is None:
            raise ValueError("typesはNoneであってはなりません（空リストは許可されます）")

        if self.last_review_time is None:
            if (
                self.estimated_closure_period_start is not None
                or self.estimated_closure_period_end is not None
            ):
                raise ValueError(
                    "last_review_timeがNoneの場合、estimated_closure_period_startと"
                    "estimated_closure_period_endは共にNoneである必要があります"
                )

        if (
            self.estimated_closure_period_start is not None
            and self.estimated_closure_period_end is not None
        ):
            if self.estimated_closure_period_start > self.estimated_closure_period_end:
                raise ValueError(
                    "estimated_closure_period_startはestimated_closure_period_end"
                    "以下である必要があります: "
                    f"{self.estimated_closure_period_start} > "
                    f"{self.estimated_closure_period_end}"
                )

        if self.data_fetched_at > datetime.now():
            raise ValueError(
                f"data_fetched_atは未来の時刻であってはなりません: {self.data_fetched_at}"
            )


@dataclass(frozen=True)
class PlaceDetailsResult:
    """Place Details APIの生レスポンスを表す型

    Attributes:
        place_id: Google Places APIのPlace ID。
        name: スポット名。
        location: スポットの位置情報。
        business_status: Places APIの営業状態。
        types: 業種・ジャンルタグ配列。
        address: 住所。取得できない場合はNone。
        phone_number: 電話番号。取得できない場合はNone。
        latest_review_time: 取得できた最新レビューの投稿時刻。
            レビューが存在しない場合はNone。
    """

    place_id: str
    name: str
    location: GeoPoint
    business_status: BusinessStatus
    types: list[str]
    address: str | None
    phone_number: str | None
    latest_review_time: datetime | None


class PlacesApiError(Exception):
    """Google Places API (Place Details API) 呼び出し失敗を表す例外。

    レート制限超過（429相当）、APIキーの無効化・権限不足（403相当）、
    対象place_idが存在しない（404相当）、ネットワークタイムアウト等の場合に
    `PlacesApiClient.get_place_details()`から発生させる（design.md エラーシナリオ6・7）。
    """


class PlacesApiClient(Protocol):
    """Google Places API (Place Details API) クライアント"""

    def get_place_details(self, place_id: str) -> PlaceDetailsResult:
        """指定`place_id`の最新詳細情報を取得する。

        レート制限・APIキー無効時は`PlacesApiError`を発生させる。
        """
        ...


class MockPlacesApiClient:
    """テスト用の`PlacesApiClient`実装。

    `place_id`をキーとした固定の`PlaceDetailsResult`辞書を保持し、
    `get_place_details(place_id)`呼び出し時にそこから結果を返す。
    `error_place_ids`に含まれる`place_id`が指定された場合は
    `PlacesApiError`を発生させ、API呼び出し失敗を模擬する。
    """

    def __init__(
        self,
        details_by_place_id: dict[str, PlaceDetailsResult] | None = None,
        error_place_ids: set[str] | None = None,
    ) -> None:
        """固定レスポンスとエラーを発生させる`place_id`集合を設定する。

        Args:
            details_by_place_id: `place_id`をキーとした`PlaceDetailsResult`の辞書。
                指定しない場合は空の辞書となる。
            error_place_ids: `get_place_details()`呼び出し時に`PlacesApiError`を
                発生させる`place_id`の集合。指定しない場合は空集合となる。
        """
        self._details_by_place_id: dict[str, PlaceDetailsResult] = (
            details_by_place_id if details_by_place_id is not None else {}
        )
        self._error_place_ids: set[str] = (
            error_place_ids if error_place_ids is not None else set()
        )

    def get_place_details(self, place_id: str) -> PlaceDetailsResult:
        """`place_id`に対応する固定の`PlaceDetailsResult`を返す。

        `error_place_ids`に含まれる`place_id`、または未登録の`place_id`が
        指定された場合は`PlacesApiError`を発生させる。
        """
        if place_id in self._error_place_ids:
            raise PlacesApiError(f"Places API呼び出しに失敗しました: {place_id}")
        if place_id not in self._details_by_place_id:
            raise PlacesApiError(f"対象place_idが見つかりません: {place_id}")
        return self._details_by_place_id[place_id]


@dataclass(frozen=True)
class SyncResult:
    """同期バッチの実行結果

    Attributes:
        processed_count: 正常にPlace Details APIレスポンスを取得できた件数。
        detected_closure_count: `CLOSED_PERMANENTLY`が検知された件数。
        error_count: Places API呼び出しが失敗した件数。
    """

    processed_count: int
    detected_closure_count: int
    error_count: int


class VacantPropertyRepository(Protocol):
    """居抜き物件候補リポジトリ（Cloud SQL for PostgreSQLをバックエンドとする）"""

    def upsert_by_place_id(self, candidate: VacantPropertyCandidate) -> None:
        """`place_id`で既存レコードとの重複を判定し、存在すれば更新、

        なければ新規作成する(UPSERT)。
        """
        ...

    def search_by_business_status_and_type(
        self,
        location: GeoPoint,
        radius_km: float,
        business_status: BusinessStatus,
        types: list[str] | None,
        limit: int,
    ) -> list[VacantPropertyCandidate]:
        """`location`から半径`radius_km`以内かつ、指定した`business_status`に

        一致し、`types`が指定されている場合はそのいずれかのタグを含む候補を返す。
        """
        ...

    def get_by_place_id(self, place_id: str) -> VacantPropertyCandidate | None:
        """`place_id`に一致する居抜き物件候補を返す。存在しない場合はNoneを返す。"""
        ...

    def search_in_bounds(
        self,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        limit: int,
    ) -> list[VacantPropertyCandidate]:
        """指定した緯度経度の矩形範囲内にある居抜き物件候補を返す（管理画面のマップ表示用）。"""
        ...

    def update_details(
        self,
        place_id: str,
        rent_yen: int | None,
        area_sqm: float | None,
        built_year: int | None,
        structure: str | None,
    ) -> None:
        """管理画面での手動編集項目（賃料・面積・築年数・構造）を更新する。

        `None`が渡された項目も含め、すべて指定値で上書きする
        （値をクリアする操作にも対応するため、他の更新系メソッドとは異なり
        COALESCEによる部分更新は行わない）。
        """
        ...


class InMemoryVacantPropertyRepository:
    """テスト用のインメモリ`VacantPropertyRepository`実装。

    内部に`place_id`をキーとした辞書として`VacantPropertyCandidate`を保持する。
    """

    def __init__(
        self, candidates: list[VacantPropertyCandidate] | None = None
    ) -> None:
        """内部データを初期化する。

        Args:
            candidates: 初期データとして保持する居抜き物件候補のリスト。
                指定しない場合は空の辞書から開始する。
        """
        self._candidates_by_place_id: dict[str, VacantPropertyCandidate] = {}
        if candidates:
            for candidate in candidates:
                self._candidates_by_place_id[candidate.place_id] = candidate

    def upsert_by_place_id(self, candidate: VacantPropertyCandidate) -> None:
        """`place_id`をキーとして、既存レコードがあれば上書き、なければ追加する。

        （Requirements 13.2, 13.3）
        """
        self._candidates_by_place_id[candidate.place_id] = candidate

    def search_by_business_status_and_type(
        self,
        location: GeoPoint,
        radius_km: float,
        business_status: BusinessStatus,
        types: list[str] | None,
        limit: int,
    ) -> list[VacantPropertyCandidate]:
        """`location`から半径`radius_km`以内かつ`business_status`が一致し、

        `types`指定時は積集合が空でない候補を、距離が近い順に`limit`件以下で返す。

        本タスク（タスク14）では簡易実装とし、詳細な仕様はタスク16で実装する。
        データベースへの読み取り専用操作を模し、内部状態を変更しない。
        """
        candidates = [
            candidate
            for candidate in self._candidates_by_place_id.values()
            if candidate.business_status == business_status
            and haversine_distance_km(location, candidate.location) <= radius_km
        ]

        if types is not None:
            type_set = set(types)
            candidates = [
                candidate
                for candidate in candidates
                if type_set & set(candidate.types)
            ]

        candidates.sort(
            key=lambda candidate: haversine_distance_km(location, candidate.location)
        )
        return candidates[:limit]

    def get_by_place_id(self, place_id: str) -> VacantPropertyCandidate | None:
        """`place_id`に一致する居抜き物件候補を内部辞書から返す。存在しない場合はNoneを返す。"""
        return self._candidates_by_place_id.get(place_id)

    def search_in_bounds(
        self,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        limit: int,
    ) -> list[VacantPropertyCandidate]:
        """緯度経度の矩形範囲内にある居抜き物件候補を、内部辞書の順序で最大`limit`件返す。"""
        matched = [
            candidate
            for candidate in self._candidates_by_place_id.values()
            if min_latitude <= candidate.location.latitude <= max_latitude
            and min_longitude <= candidate.location.longitude <= max_longitude
        ]
        return matched[:limit]

    def update_details(
        self,
        place_id: str,
        rent_yen: int | None,
        area_sqm: float | None,
        built_year: int | None,
        structure: str | None,
    ) -> None:
        """`place_id`に一致する居抜き物件候補の手動編集項目を上書きする。

        Raises:
            ValueError: 対象の`place_id`が見つからない場合。
        """
        existing = self._candidates_by_place_id.get(place_id)
        if existing is None:
            raise ValueError(f"居抜き物件候補が見つかりません: {place_id}")
        self._candidates_by_place_id[place_id] = VacantPropertyCandidate(
            place_id=existing.place_id,
            name=existing.name,
            location=existing.location,
            business_status=existing.business_status,
            types=existing.types,
            address=existing.address,
            phone_number=existing.phone_number,
            data_fetched_at=existing.data_fetched_at,
            last_review_time=existing.last_review_time,
            estimated_closure_period_start=existing.estimated_closure_period_start,
            estimated_closure_period_end=existing.estimated_closure_period_end,
            rent_yen=rent_yen,
            area_sqm=area_sqm,
            built_year=built_year,
            structure=structure,
        )

    def __len__(self) -> int:
        """保持している居抜き物件候補の件数を返す（テストでの副作用確認に使用）。"""
        return len(self._candidates_by_place_id)


def search_vacant_properties(
    vacant_property_repository: VacantPropertyRepository,
    location: GeoPoint,
    radius_km: float,
    business_status: BusinessStatus,
    types: list[str] | None,
    limit: int,
) -> list[VacantPropertyCandidate]:
    """指定した位置・半径・business_status・業種タグに合致する

    居抜き物件候補を返す。

    事前条件を満たさない場合は`ValueError`を発生させる
    （Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6）。

    Args:
        vacant_property_repository: 検索対象のリポジトリ。
        location: 検索基準となる位置情報。`GeoPoint`の`__post_init__`で
            緯度経度の範囲は既に検証されている。
        radius_km: 検索半径（キロメートル）。正の数であること。
        business_status: 絞り込み対象の営業状態。
        types: 業種・ジャンルタグによる絞り込み条件。Noneの場合は
            タグによる絞り込みを行わない。
        limit: 取得件数の上限。1以上の整数であること。

    Returns:
        `vacant_property_repository.search_by_business_status_and_type(...)`
        の戻り値をそのまま返す。

    Raises:
        ValueError: `radius_km`が0以下、または`limit`が1未満の場合。
    """
    if radius_km <= 0:
        raise ValueError(f"radius_kmは正の数である必要があります: {radius_km}")
    if limit < 1:
        raise ValueError(f"limitは1以上である必要があります: {limit}")

    return vacant_property_repository.search_by_business_status_and_type(
        location, radius_km, business_status, types, limit
    )


def estimate_closure_period(
    data_fetched_at: datetime, last_review_time: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """データ取得時刻と最新レビュー時刻から、

    「最終確認時点でまだ営業中だった可能性が高い時期」の推定レンジを返す。
    厳密な廃業日ではなく代理データからの推定レンジとして扱う。

    Args:
        data_fetched_at: このレコードのデータをGoogleから取得した時刻。
            未来の時刻であってはならない。
        last_review_time: 取得できた最新レビューの投稿時刻。
            レビューが存在しない場合はNone。

    Returns:
        `last_review_time`がNoneの場合は`(None, None)`。
        非Noneの場合は`(last_review_time, data_fetched_at)`。

    Requirements: 14.1, 14.2, 14.3, 14.4
    """
    if last_review_time is None:
        return None, None
    return last_review_time, data_fetched_at


def sync_vacant_properties(
    places_api_client: PlacesApiClient,
    vacant_property_repository: VacantPropertyRepository,
    target_place_ids: list[str],
) -> SyncResult:
    """対象place_id群についてPlace Details APIを呼び出し、business_statusを確認する。

    `CLOSED_PERMANENTLY`を検知した場合、廃業時期を推定してUPSERTする。
    既存レコードのリフレッシュ（30日以内の再取得）も兼ねる。

    Places API呼び出しが失敗した`place_id`はスキップして`error_count`に加算し、
    処理は中断せず継続する（部分失敗許容）。

    Args:
        places_api_client: Place Details APIを呼び出すクライアント。
        vacant_property_repository: 検知結果をUPSERTするリポジトリ。
        target_place_ids: 同期対象の`place_id`のリスト。空リストであってもよい。

    Returns:
        `SyncResult`（`processed_count`, `detected_closure_count`, `error_count`）。

    Requirements: 13.1, 13.3, 13.4
    """
    processed = 0
    detected = 0
    errors = 0
    for place_id in target_place_ids:
        try:
            details = places_api_client.get_place_details(place_id)
        except PlacesApiError:
            errors += 1
            continue

        processed += 1
        if details.business_status == BusinessStatus.CLOSED_PERMANENTLY:
            start, end = estimate_closure_period(
                data_fetched_at=datetime.now(),
                last_review_time=details.latest_review_time,
            )
            candidate = VacantPropertyCandidate(
                place_id=details.place_id,
                name=details.name,
                location=details.location,
                business_status=details.business_status,
                types=details.types,
                address=details.address,
                phone_number=details.phone_number,
                data_fetched_at=datetime.now(),
                last_review_time=details.latest_review_time,
                estimated_closure_period_start=start,
                estimated_closure_period_end=end,
            )
            vacant_property_repository.upsert_by_place_id(candidate)
            detected += 1
    return SyncResult(
        processed_count=processed, detected_closure_count=detected, error_count=errors
    )

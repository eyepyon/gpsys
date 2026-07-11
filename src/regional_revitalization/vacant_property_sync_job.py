"""居抜き物件同期サービス（Cloud Run Jobs）のエントリポイント。

`design.md`の「コンポーネント5: 居抜き物件同期サービス
(VacantPropertySyncService)」に基づき、Cloud SchedulerによってトリガーされるCloud
Run Jobsとして定期実行されるバッチスクリプトを実装する。

**環境変数（`terraform/modules/cloudrun_jobs_vacant_property_sync/main.tf`と対応）**:

- ``DB_CONNECTION_JSON``: DB接続情報（host/port/database/user/passwordを含む
  JSON文字列）。Secret Manager経由で環境変数にマウントされる。
- ``PLACES_API_KEY``: Places APIキー。Secret Manager経由で環境変数にマウントされる。
- ``GCP_PROJECT_ID``: GCPプロジェクトID。
- ``TARGET_PLACE_IDS``: 同期対象の`place_id`をカンマ区切りで連結した文字列。

**Places APIキーの取得方針（Requirements 13.6）**:
Cloud Run Jobs実行時は、Terraform側の`secret_key_ref`設定により、Secret Manager
に登録されたPlaces APIキーが環境変数`PLACES_API_KEY`へ自動的にマウントされる。
そのため、アプリケーションコード側では通常、環境変数を読み取るだけでよく、
Secret Manager APIを直接呼び出す必要はない。ただし、環境変数`PLACES_API_KEY`が
未設定で、代わりに環境変数`PLACES_API_KEY_SECRET_NAME`（Secret Managerの
シークレットバージョンの完全なリソース名）が指定された場合には、
`google-cloud-secret-manager`パッケージを用いてSecret Managerから直接
APIキーを取得するフォールバック経路も用意する。当該パッケージが実行環境に
インストールされていない場合でも本モジュールの読み込み自体が失敗しないよう、
importは関数内で`try/except ImportError`により保護する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from regional_revitalization.models import GeoPoint
from regional_revitalization.postgres_vacant_property_repository import (
    PostgresVacantPropertyRepository,
)
from regional_revitalization.vacant_property import (
    BusinessStatus,
    PlaceDetailsResult,
    PlacesApiClient,
    PlacesApiError,
    SyncResult,
    VacantPropertyRepository,
    sync_vacant_properties,
)

if TYPE_CHECKING:
    # 型チェック時のみ`asyncpg`を参照する。実行時に未インストールでも
    # importエラーにならないようにするため、型ヒント専用の参照に留める。
    import asyncpg

logger = logging.getLogger(__name__)

#: DB接続情報JSON（`DB_CONNECTION_JSON`）に必須のキー一覧。
_REQUIRED_DB_CONNECTION_KEYS = ("host", "port", "database", "user", "password")

#: Places API (Place Details API) v1のリクエストで取得するフィールド一覧。
_PLACES_API_FIELD_MASK = (
    "id,displayName,location,businessStatus,types,"
    "formattedAddress,internationalPhoneNumber,reviews"
)


class ConfigurationError(Exception):
    """環境変数の欠落・形式不正等、ジョブ起動時の設定不備を表す例外。"""


@dataclass(frozen=True)
class JobConfig:
    """Cloud Run Jobs実行に必要な設定値。

    Attributes:
        db_connection: DB接続情報の辞書（`host`, `port`, `database`, `user`,
            `password`の各キーを含む）。
        places_api_key: Places APIキー。
        gcp_project_id: GCPプロジェクトID。
        target_place_ids: 同期対象の`place_id`のリスト（1件以上）。
    """

    db_connection: dict[str, Any]
    places_api_key: str
    gcp_project_id: str
    target_place_ids: list[str]


def _get_required_env(name: str) -> str:
    """必須の環境変数を取得する。

    Args:
        name: 環境変数名。

    Returns:
        環境変数の値。

    Raises:
        ConfigurationError: 環境変数が未設定、または空文字列の場合。
    """
    value = os.environ.get(name)
    if value is None or value == "":
        raise ConfigurationError(f"環境変数{name}が設定されていません")
    return value


def parse_target_place_ids(raw: str) -> list[str]:
    """カンマ区切り文字列を`place_id`のリストへ変換する。

    各要素の前後の空白は除去し、空文字列の要素は無視する。

    Args:
        raw: `TARGET_PLACE_IDS`環境変数の値（カンマ区切り文字列）。

    Returns:
        `place_id`のリスト（1件以上）。

    Raises:
        ConfigurationError: 有効な`place_id`が1件も含まれない場合。
    """
    place_ids = [item.strip() for item in raw.split(",")]
    place_ids = [item for item in place_ids if item != ""]
    if not place_ids:
        raise ConfigurationError(
            "TARGET_PLACE_IDSに有効なplace_idが1件も含まれていません"
        )
    return place_ids


def parse_db_connection_json(raw: str) -> dict[str, Any]:
    """`DB_CONNECTION_JSON`環境変数の値をパースし、DB接続情報の辞書を返す。

    Args:
        raw: `DB_CONNECTION_JSON`環境変数の値（JSON文字列）。

    Returns:
        DB接続情報の辞書（`host`, `port`, `database`, `user`, `password`）。

    Raises:
        ConfigurationError: JSON解析に失敗した場合、または必須キーが
            不足している場合。
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"DB_CONNECTION_JSONのJSON解析に失敗しました: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigurationError(
            "DB_CONNECTION_JSONはJSONオブジェクトである必要があります"
        )

    missing_keys = [key for key in _REQUIRED_DB_CONNECTION_KEYS if key not in data]
    if missing_keys:
        raise ConfigurationError(
            f"DB_CONNECTION_JSONに必須キーが不足しています: {missing_keys}"
        )
    return data


def get_places_api_key() -> str:
    """Places APIキーを取得する（Requirements 13.6）。

    Cloud Run実行時は、Terraform側の`secret_key_ref`設定によりSecret Manager
    に登録されたAPIキーが環境変数`PLACES_API_KEY`へ自動的にマウントされるため、
    通常は環境変数を読み取るだけでよい。

    環境変数`PLACES_API_KEY`が未設定の場合は、環境変数
    `PLACES_API_KEY_SECRET_NAME`（Secret Managerのシークレットバージョンの
    完全なリソース名、例:
    ``projects/PROJECT_ID/secrets/SECRET_ID/versions/latest``）が指定されて
    いれば、`google-cloud-secret-manager`パッケージを用いてSecret Managerから
    直接APIキーを取得するフォールバック経路を試行する。

    Returns:
        Places APIキー。

    Raises:
        ConfigurationError: 環境変数`PLACES_API_KEY`・
            `PLACES_API_KEY_SECRET_NAME`のいずれも未設定の場合、または
            Secret Manager経由の取得に必要なパッケージが利用できない場合。
    """
    api_key = os.environ.get("PLACES_API_KEY")
    if api_key:
        return api_key

    secret_name = os.environ.get("PLACES_API_KEY_SECRET_NAME")
    if not secret_name:
        raise ConfigurationError(
            "環境変数PLACES_API_KEYが設定されておらず、"
            "PLACES_API_KEY_SECRET_NAMEも指定されていないため"
            "Places APIキーを取得できません"
        )

    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - テスト環境に未インストールの場合
        raise ConfigurationError(
            "Secret Manager経由でのPlaces APIキー取得には"
            "google-cloud-secret-managerパッケージが必要です"
        ) from exc

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=secret_name)
    return response.payload.data.decode("utf-8")


def load_config_from_env() -> JobConfig:
    """環境変数からジョブ実行に必要な設定値をすべて読み込む。

    Returns:
        `JobConfig`。

    Raises:
        ConfigurationError: 必須の環境変数が欠落している、または
            形式が不正な場合。
    """
    db_connection = parse_db_connection_json(_get_required_env("DB_CONNECTION_JSON"))
    gcp_project_id = _get_required_env("GCP_PROJECT_ID")
    target_place_ids = parse_target_place_ids(_get_required_env("TARGET_PLACE_IDS"))
    places_api_key = get_places_api_key()

    return JobConfig(
        db_connection=db_connection,
        places_api_key=places_api_key,
        gcp_project_id=gcp_project_id,
        target_place_ids=target_place_ids,
    )


def build_dsn(db_connection: dict[str, Any]) -> str:
    """DB接続情報の辞書から`asyncpg`用のDSN文字列を組み立てる。

    Args:
        db_connection: `host`, `port`, `database`, `user`, `password`を
            含む辞書。

    Returns:
        ``postgresql://user:password@host:port/database``形式のDSN文字列。
    """
    return (
        f"postgresql://{db_connection['user']}:{db_connection['password']}"
        f"@{db_connection['host']}:{db_connection['port']}/{db_connection['database']}"
    )


def _parse_place_details_response(place_id: str, data: dict[str, Any]) -> PlaceDetailsResult:
    """Places API (Place Details API) v1のレスポンスJSONを`PlaceDetailsResult`へ

    変換する。

    Args:
        place_id: リクエスト対象の`place_id`。
        data: レスポンスJSONをデコードした辞書。

    Returns:
        変換された`PlaceDetailsResult`。

    Raises:
        PlacesApiError: レスポンスの必須フィールドが欠落・不正な場合。
    """
    try:
        name = data["displayName"]["text"]
        location_data = data["location"]
        location = GeoPoint(
            latitude=location_data["latitude"], longitude=location_data["longitude"]
        )
        business_status = BusinessStatus(data["businessStatus"])
        types = list(data.get("types", []))
        address = data.get("formattedAddress")
        phone_number = data.get("internationalPhoneNumber")

        latest_review_time: datetime | None = None
        reviews = data.get("reviews") or []
        if reviews:
            publish_time_raw = reviews[0].get("publishTime")
            if publish_time_raw:
                latest_review_time = datetime.fromisoformat(
                    publish_time_raw.replace("Z", "+00:00")
                )
    except (KeyError, ValueError) as exc:
        raise PlacesApiError(
            f"Places APIレスポンスの解析に失敗しました: place_id={place_id}: {exc}"
        ) from exc

    return PlaceDetailsResult(
        place_id=place_id,
        name=name,
        location=location,
        business_status=business_status,
        types=types,
        address=address,
        phone_number=phone_number,
        latest_review_time=latest_review_time,
    )


class RealPlacesApiClient:
    """Google Places API (Place Details API) v1を実際にHTTP呼び出しする

    `PlacesApiClient`実装（スケルトン）。

    `httpx`パッケージを用いてHTTP GETリクエストを送信する。`httpx`が実行環境に
    インストールされていない場合でも本モジュールの読み込み自体は失敗させず、
    実際にインスタンス化された時点で`ConfigurationError`を発生させる。
    """

    _ENDPOINT_TEMPLATE = "https://places.googleapis.com/v1/places/{place_id}"

    def __init__(self, api_key: str, timeout_seconds: float = 10.0) -> None:
        """APIキーとタイムアウト秒数を設定して初期化する。

        Args:
            api_key: Places APIキー。
            timeout_seconds: HTTPリクエストのタイムアウト秒数。

        Raises:
            ConfigurationError: `httpx`パッケージが利用できない場合。
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - テスト環境に未インストールの場合
            raise ConfigurationError(
                "Places API呼び出しにはhttpxパッケージが必要です"
            ) from exc

        self._httpx = httpx
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def get_place_details(self, place_id: str) -> PlaceDetailsResult:
        """指定`place_id`の最新詳細情報をPlace Details API呼び出しで取得する。

        レート制限・APIキー無効・ネットワークエラー等の場合は`PlacesApiError`を
        発生させる（design.md エラーシナリオ6・7）。

        Args:
            place_id: 取得対象の`place_id`。

        Returns:
            変換された`PlaceDetailsResult`。

        Raises:
            PlacesApiError: HTTPリクエストが失敗、またはレスポンスの解析に
                失敗した場合。
        """
        url = self._ENDPOINT_TEMPLATE.format(place_id=place_id)
        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _PLACES_API_FIELD_MASK,
        }
        try:
            response = self._httpx.get(
                url, headers=headers, timeout=self._timeout_seconds
            )
            response.raise_for_status()
        except self._httpx.HTTPError as exc:
            raise PlacesApiError(
                f"Places API呼び出しに失敗しました: place_id={place_id}: {exc}"
            ) from exc

        return _parse_place_details_response(place_id, response.json())


class _AsyncToSyncVacantPropertyRepository:
    """非同期実装の`PostgresVacantPropertyRepository`を、

    `sync_vacant_properties()`が要求する同期の`VacantPropertyRepository`
    インターフェースへ適合させるアダプタ。

    ジョブ全体で単一の`asyncio`イベントループを共有し、各メソッド呼び出しごとに
    `run_until_complete()`で対応する非同期コルーチンを実行する。
    """

    def __init__(
        self,
        async_repository: PostgresVacantPropertyRepository,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """ラップ対象の非同期リポジトリと、実行に使うイベントループを設定する。

        Args:
            async_repository: ラップ対象の`PostgresVacantPropertyRepository`。
            loop: コルーチン実行に使う`asyncio`イベントループ。
        """
        self._async_repository = async_repository
        self._loop = loop

    def upsert_by_place_id(self, candidate: Any) -> None:
        """非同期の`upsert_by_place_id()`を同期的に実行する。"""
        self._loop.run_until_complete(
            self._async_repository.upsert_by_place_id(candidate)
        )

    def search_by_business_status_and_type(
        self,
        location: GeoPoint,
        radius_km: float,
        business_status: BusinessStatus,
        types: list[str] | None,
        limit: int,
    ) -> list[Any]:
        """非同期の`search_by_business_status_and_type()`を同期的に実行する。"""
        return self._loop.run_until_complete(
            self._async_repository.search_by_business_status_and_type(
                location, radius_km, business_status, types, limit
            )
        )


def _create_sync_repository(
    db_connection: dict[str, Any], loop: asyncio.AbstractEventLoop
) -> tuple[VacantPropertyRepository, "asyncpg.Pool"]:
    """DB接続情報からコネクションプールを作成し、同期インターフェースの

    `VacantPropertyRepository`を組み立てる。

    Args:
        db_connection: DB接続情報の辞書。
        loop: コネクションプール作成・クエリ実行に使う`asyncio`イベントループ。

    Returns:
        同期インターフェースでラップされたリポジトリと、作成したコネクション
        プールのペア（呼び出し側でプールのクローズ処理を行うために返す）。

    Raises:
        ConfigurationError: `asyncpg`パッケージが利用できない場合。
    """
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - テスト環境に未インストールの場合
        raise ConfigurationError(
            "Cloud SQLへの接続にはasyncpgパッケージが必要です"
        ) from exc

    dsn = build_dsn(db_connection)
    pool = loop.run_until_complete(asyncpg.create_pool(dsn))
    async_repository = PostgresVacantPropertyRepository(pool)
    return _AsyncToSyncVacantPropertyRepository(async_repository, loop), pool


def run_sync_job(
    places_api_client: PlacesApiClient,
    vacant_property_repository: VacantPropertyRepository,
    target_place_ids: list[str],
) -> SyncResult:
    """`sync_vacant_properties()`を呼び出し、結果をログ出力する。

    Args:
        places_api_client: Place Details APIを呼び出すクライアント。
        vacant_property_repository: 検知結果をUPSERTするリポジトリ。
        target_place_ids: 同期対象の`place_id`のリスト。

    Returns:
        `sync_vacant_properties()`の戻り値（`SyncResult`）。
    """
    result = sync_vacant_properties(
        places_api_client, vacant_property_repository, target_place_ids
    )
    logger.info(
        "居抜き物件同期処理が完了しました: processed_count=%d, "
        "detected_closure_count=%d, error_count=%d",
        result.processed_count,
        result.detected_closure_count,
        result.error_count,
    )
    return result


def main() -> SyncResult:
    """Cloud Run Jobsのエントリポイント。

    環境変数から設定値を読み込み、Cloud SQL（PostgreSQL）へのコネクション
    プールとPlaces APIクライアントを組み立て、`sync_vacant_properties()`を
    呼び出す。

    Returns:
        `sync_vacant_properties()`の戻り値（`SyncResult`）。
    """
    logging.basicConfig(level=logging.INFO)

    config = load_config_from_env()
    logger.info(
        "居抜き物件同期ジョブを開始します: gcp_project_id=%s, target_place_ids=%d件",
        config.gcp_project_id,
        len(config.target_place_ids),
    )

    loop = asyncio.new_event_loop()
    pool = None
    try:
        vacant_property_repository, pool = _create_sync_repository(
            config.db_connection, loop
        )
        places_api_client = RealPlacesApiClient(api_key=config.places_api_key)
        return run_sync_job(
            places_api_client, vacant_property_repository, config.target_place_ids
        )
    finally:
        if pool is not None:
            loop.run_until_complete(pool.close())
        loop.close()


if __name__ == "__main__":
    main()

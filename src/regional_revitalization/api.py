"""アプリ本体サービス（APIRun）のFastAPI APIエンドポイント実装。

`design.md`の「コンポーネント1: アプリ本体サービス (APIRun)」に基づき、
`POST /consultations`（相談応答）、`POST /resources`（地域資源登録）の
2つのエンドポイントを実装する。

各エンドポイントは、これまでのタスクで実装した関数群
（`generate_consultation_response()`, `register_resource()`）を呼び出す
だけの薄いレイヤーとし、ビジネスロジックはFastAPI層に持たない。

**依存性注入の方針**: `ResourceRepository`, `StorageClient`,
`InferenceClient`のインスタンスはモジュールレベルのグローバル変数として
保持し、FastAPIの`Depends`経由で各エンドポイントに注入する。デフォルトは
テスト・ローカル実行向けのインメモリ/モック実装とし、実運用時には
`app.dependency_overrides`または`set_resource_repository()`等の関数で
実装（Cloud SQL/Cloud Storage/推論サービスクライアント）に切り替える。

**ステータスコードの方針（Requirements 1.1, 1.2, 1.3, 1.5, 5.1）**:
- リクエストボディの型・必須項目が不正な場合、FastAPI/Pydanticの検証により
  自動的に422が返る（Pydanticの標準動作）
- `generate_consultation_response()`/`register_resource()`が`ValueError`
  （`query_text`空文字列、`radius_km<=0`、`name`等の空文字列など、
  アプリケーション側の検証エラー）を発生させた場合は400を返す
- 推論サービス呼び出し失敗時（`generate_consultation_response`から伝播した
  例外）は502を返す
- ストレージアップロード失敗時（`register_resource`から伝播した例外）は
  503を返す
- `search_vacant_properties()`が`ValueError`（`radius_km<=0`、`limit<1`、
  緯度経度範囲外など）を発生させた場合は400を返す
- その他の予期しない例外は500を返す
"""

from __future__ import annotations

import base64
import binascii
import inspect
import json
import logging
import os
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from regional_revitalization.admin_auth import (
    AdminUser,
    AdminUserRepository,
    InMemoryAdminUserRepository,
    authenticate,
    create_admin_user,
    hash_password,
    resolve_session,
)
from regional_revitalization.admin_stats import (
    AdminStatsRepository,
    InMemoryAdminStatsRepository,
)
from regional_revitalization.consultation import generate_consultation_response
from regional_revitalization.inference import InferenceClient, MockInferenceClient
from regional_revitalization.models import (
    ConsultationRequest,
    GeoPoint,
    RegionalResource,
)
from regional_revitalization.places_search import (
    InMemoryPlacesSearchResultRepository,
    MockPlacesSearchClient,
    PlacesSearchClient,
    PlacesSearchResult,
    PlacesSearchResultRepository,
    execute_places_search,
    register_search_result,
)
from regional_revitalization.registration import register_resource
from regional_revitalization.repository import (
    InMemoryResourceRepository,
    ResourceRepository,
)
from regional_revitalization.resource_management import (
    delete_resource,
    search_resources_in_bounds,
    update_resource,
)
from regional_revitalization.search_history import (
    InMemorySearchRequestRepository,
    SearchRequest,
    SearchRequestRepository,
    record_search_request,
)
from regional_revitalization.update_request import (
    InMemoryUpdateRequestRepository,
    UpdateRequest,
    UpdateRequestRepository,
    approve_request,
    reject_request,
    submit_update_request,
)
from regional_revitalization.storage import InMemoryStorageClient, StorageClient
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    PlacesApiError,
    VacantPropertyCandidate,
    VacantPropertyRepository,
    search_vacant_properties,
)
from regional_revitalization.vacant_property_management import (
    search_vacant_properties_in_bounds,
    update_vacant_property_details,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """アプリ起動時に実運用実装への差し替えを行うライフスパンハンドラ。"""
    await _bootstrap_production_dependencies()
    yield


app = FastAPI(
    title="地方創生支援システム アプリ本体サービス (APIRun)", lifespan=_lifespan
)

# --------------------------------------------------------------------------
# CORS設定（動作確認用フロント画面からのアクセスを許可する）
# --------------------------------------------------------------------------
# 環境変数`CORS_ALLOWED_ORIGINS`にカンマ区切りのオリジン一覧を指定した場合のみ
# CORSを許可する（未設定時は既定でCORS無効。ブラウザから直接呼び出す
# 確認用フロント画面等、必要な場合にのみ明示的に有効化する運用とする）。
_cors_allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in _cors_allowed_origins.split(",") if origin.strip()
        ],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )


# --------------------------------------------------------------------------
# 依存性注入用の共有インスタンス
# --------------------------------------------------------------------------
# デフォルトはインメモリ/モック実装とする。実運用時はCloud SQL/Cloud Storage/
# 推論サービスクライアントの実装に差し替える（`set_*`関数、または
# `app.dependency_overrides`を利用する）。
_resource_repository: ResourceRepository = InMemoryResourceRepository()
_storage_client: StorageClient = InMemoryStorageClient()
_inference_client: InferenceClient = MockInferenceClient()
_vacant_property_repository: VacantPropertyRepository = (
    InMemoryVacantPropertyRepository()
)
_admin_user_repository: AdminUserRepository = InMemoryAdminUserRepository()
_admin_stats_repository: AdminStatsRepository = InMemoryAdminStatsRepository(
    resource_repository=_resource_repository,
    vacant_property_repository=_vacant_property_repository,
    admin_user_repository=_admin_user_repository,
)
_update_request_repository: UpdateRequestRepository = InMemoryUpdateRequestRepository()
_search_request_repository: SearchRequestRepository = InMemorySearchRequestRepository()
_places_search_client: PlacesSearchClient = MockPlacesSearchClient()
_places_search_result_repository: PlacesSearchResultRepository = (
    InMemoryPlacesSearchResultRepository()
)


def get_resource_repository() -> ResourceRepository:
    """共有の`ResourceRepository`インスタンスを返す（`Depends`用）。"""
    return _resource_repository


def get_storage_client() -> StorageClient:
    """共有の`StorageClient`インスタンスを返す（`Depends`用）。"""
    return _storage_client


def get_inference_client() -> InferenceClient:
    """共有の`InferenceClient`インスタンスを返す（`Depends`用）。"""
    return _inference_client


def get_vacant_property_repository() -> VacantPropertyRepository:
    """共有の`VacantPropertyRepository`インスタンスを返す（`Depends`用）。"""
    return _vacant_property_repository


def get_admin_user_repository() -> AdminUserRepository:
    """共有の`AdminUserRepository`インスタンスを返す（`Depends`用）。"""
    return _admin_user_repository


def get_admin_stats_repository() -> AdminStatsRepository:
    """共有の`AdminStatsRepository`インスタンスを返す（`Depends`用）。"""
    return _admin_stats_repository


def get_update_request_repository() -> UpdateRequestRepository:
    """共有の`UpdateRequestRepository`インスタンスを返す（`Depends`用）。"""
    return _update_request_repository


def get_search_request_repository() -> SearchRequestRepository:
    """共有の`SearchRequestRepository`インスタンスを返す（`Depends`用）。"""
    return _search_request_repository


def get_places_search_client() -> PlacesSearchClient:
    """共有の`PlacesSearchClient`インスタンスを返す（`Depends`用）。"""
    return _places_search_client


def get_places_search_result_repository() -> PlacesSearchResultRepository:
    """共有の`PlacesSearchResultRepository`インスタンスを返す（`Depends`用）。"""
    return _places_search_result_repository


def set_resource_repository(repository: ResourceRepository) -> None:
    """共有の`ResourceRepository`インスタンスを差し替える。

    実運用環境（Cloud SQL接続等）や結合テストで、デフォルトの
    インメモリ実装から実装を切り替えるために使用する。
    """
    global _resource_repository
    _resource_repository = repository


def set_storage_client(client: StorageClient) -> None:
    """共有の`StorageClient`インスタンスを差し替える。"""
    global _storage_client
    _storage_client = client


def set_inference_client(client: InferenceClient) -> None:
    """共有の`InferenceClient`インスタンスを差し替える。"""
    global _inference_client
    _inference_client = client


def set_vacant_property_repository(repository: VacantPropertyRepository) -> None:
    """共有の`VacantPropertyRepository`インスタンスを差し替える。

    実運用環境（Cloud SQL接続等）や結合テストで、デフォルトの
    インメモリ実装から実装を切り替えるために使用する。
    """
    global _vacant_property_repository
    _vacant_property_repository = repository


def set_admin_user_repository(repository: AdminUserRepository) -> None:
    """共有の`AdminUserRepository`インスタンスを差し替える。"""
    global _admin_user_repository
    _admin_user_repository = repository


def set_admin_stats_repository(repository: AdminStatsRepository) -> None:
    """共有の`AdminStatsRepository`インスタンスを差し替える。"""
    global _admin_stats_repository
    _admin_stats_repository = repository


def set_update_request_repository(repository: UpdateRequestRepository) -> None:
    """共有の`UpdateRequestRepository`インスタンスを差し替える。"""
    global _update_request_repository
    _update_request_repository = repository


def set_search_request_repository(repository: SearchRequestRepository) -> None:
    """共有の`SearchRequestRepository`インスタンスを差し替える。"""
    global _search_request_repository
    _search_request_repository = repository


def set_places_search_client(client: PlacesSearchClient) -> None:
    """共有の`PlacesSearchClient`インスタンスを差し替える。"""
    global _places_search_client
    _places_search_client = client


def set_places_search_result_repository(
    repository: PlacesSearchResultRepository,
) -> None:
    """共有の`PlacesSearchResultRepository`インスタンスを差し替える。"""
    global _places_search_result_repository
    _places_search_result_repository = repository


# --------------------------------------------------------------------------
# 起動時ブートストラップ（実運用実装への差し替え）
# --------------------------------------------------------------------------
# Cloud Run実行時は、環境変数`DB_CONNECTION_JSON`・`GCS_BUCKET_NAME`が
# Terraform（Secret Manager経由）で設定されるため、それらが存在する場合のみ
# インメモリ実装からCloud SQL/Cloud Storage実装へ差し替える。
# 環境変数が未設定のローカル開発・単体テストではデフォルトのインメモリ実装の
# ままとし、実DB/実バケットへの接続を試行しない。
# 本関数は`_lifespan`（FastAPIのlifespanイベントハンドラ）から呼び出される。


async def _bootstrap_production_dependencies() -> None:
    """環境変数に応じて、共有インスタンスを実運用実装へ差し替える。"""
    db_connection_json = os.environ.get("DB_CONNECTION_JSON")
    database_url = os.environ.get("DATABASE_URL")
    if db_connection_json or database_url:
        try:
            import asyncpg

            from regional_revitalization.postgres_admin_auth_repository import (
                PostgresAdminUserRepository,
            )
            from regional_revitalization.admin_stats import (
                PostgresAdminStatsRepository,
            )
            from regional_revitalization.postgres_repository import (
                PostgresResourceRepository,
            )
            from regional_revitalization.postgres_vacant_property_repository import (
                PostgresVacantPropertyRepository,
            )

            if db_connection_json:
                db_connection = json.loads(db_connection_json)
                pool = await asyncpg.create_pool(**db_connection)
            else:
                pool = await asyncpg.create_pool(database_url)
            await _apply_database_migrations(pool)
            set_resource_repository(PostgresResourceRepository(pool))
            set_vacant_property_repository(
                PostgresVacantPropertyRepository(pool)
            )
            from regional_revitalization.postgres_update_request_repository import (
                PostgresUpdateRequestRepository,
            )
            from regional_revitalization.postgres_search_history_repository import (
                PostgresSearchRequestRepository,
            )

            admin_user_repository = PostgresAdminUserRepository(pool)
            set_admin_user_repository(admin_user_repository)
            set_admin_stats_repository(PostgresAdminStatsRepository(pool))
            set_update_request_repository(PostgresUpdateRequestRepository(pool))
            set_search_request_repository(PostgresSearchRequestRepository(pool))
            logger.info("Cloud SQL for PostgreSQLへの接続を初期化しました")

            await _bootstrap_initial_admin_user(admin_user_repository)
        except Exception:  # noqa: BLE001 - 起動失敗の原因をログに残し例外を再送する
            logger.exception("Cloud SQLへの接続初期化に失敗しました")
            raise

    bucket_name = os.environ.get("GCS_BUCKET_NAME")
    if bucket_name:
        try:
            from regional_revitalization.storage import GcsStorageClient

            set_storage_client(GcsStorageClient(bucket_name=bucket_name))
            logger.info("Cloud Storageクライアントを初期化しました: bucket=%s", bucket_name)
        except Exception:  # noqa: BLE001 - 起動失敗の原因をログに残し例外を再送する
            logger.exception("Cloud Storageクライアントの初期化に失敗しました")
            raise

    inference_url = os.environ.get("INFER_RUN_URL") or os.environ.get(
        "INFERENCE_SERVICE_URL"
    )
    if inference_url:
        try:
            from regional_revitalization.inference import HttpInferenceClient

            set_inference_client(HttpInferenceClient(base_url=inference_url))
            logger.info(
                "推論サービスクライアントを初期化しました: url=%s", inference_url
            )
        except Exception:  # noqa: BLE001 - 起動失敗の原因をログに残し例外を再送する
            logger.exception("推論サービスクライアントの初期化に失敗しました")
            raise

    # 管理画面の「この場所でGoogle Places APIを検索する」機能用のクライアント。
    # 居抜き物件同期サービス（Cloud Run Jobs）とは別に、APIRunからも
    # Places APIを呼び出すため、専用のSecret Manager経由の環境変数を用意する。
    places_api_key = os.environ.get("ADMIN_PLACES_API_KEY")
    if places_api_key:
        try:
            from regional_revitalization.real_places_search_client import (
                RealPlacesSearchClient,
            )

            set_places_search_client(RealPlacesSearchClient(api_key=places_api_key))
            logger.info("管理画面向けPlaces APIクライアントを初期化しました")
        except Exception:  # noqa: BLE001 - 起動失敗の原因をログに残し例外を再送する
            logger.exception("Places APIクライアントの初期化に失敗しました")
            raise


async def _apply_database_migrations(pool: object) -> None:
    """Apply bundled idempotent SQL migrations before serving requests."""
    migrations_dir = Path.cwd() / "migrations"
    migration_paths = sorted(migrations_dir.glob("*.sql"))
    if not migration_paths:
        raise RuntimeError(f"DBマイグレーションが見つかりません: {migrations_dir}")
    for migration_path in migration_paths:
        sql = migration_path.read_text(encoding="utf-8")
        await pool.execute(sql)  # type: ignore[attr-defined]
        logger.info("DBマイグレーションを適用しました: %s", migration_path.name)


async def _bootstrap_initial_admin_user(
    admin_user_repository: AdminUserRepository,
) -> None:
    """環境変数を基準に初期管理者を作成またはパスワード同期する。

    環境変数`ADMIN_INITIAL_USERNAME`/`ADMIN_INITIAL_PASSWORD`が両方設定されて
    いる場合のみ実行する（Terraform経由でSecret Managerから注入する想定）。
    同じユーザー名が既に存在する場合は、パスワードをSecretの値に同期する。
    これにより、管理画面へのログイン手段が皆無になる「鶏と卵」問題を避ける。
    2件目以降の管理ユーザーは、この初回アカウントでログインした管理画面上の
    ユーザー管理ページから作成する。
    """
    initial_username = os.environ.get("ADMIN_INITIAL_USERNAME")
    initial_password = os.environ.get("ADMIN_INITIAL_PASSWORD")
    if not initial_username or not initial_password:
        logger.warning(
            "管理ユーザーが1件も存在しませんが、ADMIN_INITIAL_USERNAME/"
            "ADMIN_INITIAL_PASSWORDが未設定のため初回管理者を作成できません"
        )
        return

    existing_user = await admin_user_repository.get_by_username(initial_username)
    if existing_user is not None:
        await admin_user_repository.update(
            existing_user.admin_user_id,
            display_name=None,
            password_hash=hash_password(initial_password),
            is_active=True,
        )
        logger.info(
            "初期管理ユーザーのパスワードを環境変数と同期しました: username=%s",
            initial_username,
        )
        return

    await create_admin_user(
        admin_user_repository,
        username=initial_username,
        plain_password=initial_password,
        display_name="初期管理者",
    )
    logger.info("初回管理ユーザーを作成しました: username=%s", initial_username)


# --------------------------------------------------------------------------
# リクエスト/レスポンスボディのPydanticモデル
# --------------------------------------------------------------------------


class ConsultationRequestBody(BaseModel):
    """`POST /consultations`のリクエストボディ。"""

    query_text: str = Field(..., description="利用者からの質問文")
    latitude: float = Field(..., description="利用者の位置情報（緯度）")
    longitude: float = Field(..., description="利用者の位置情報（経度）")
    radius_km: float = Field(..., description="検索半径（キロメートル）")
    top_k: int = Field(default=5, description="生成時に利用する上位件数")


class RegionalResourceBody(BaseModel):
    """相談応答レスポンス内で参照する地域資源1件分のボディ。"""

    resource_id: str
    name: str
    category: str
    description: str
    latitude: float
    longitude: float
    file_url: str | None


class ConsultationResponseBody(BaseModel):
    """`POST /consultations`のレスポンスボディ。"""

    generated_text: str
    referenced_resources: list[RegionalResourceBody]


class ResourceRegistrationRequestBody(BaseModel):
    """`POST /resources`のリクエストボディ。

    添付ファイルは任意で、base64エンコードされたバイト列として受け取る。
    """

    name: str = Field(..., description="地域資源の名称")
    category: str = Field(..., description="地域資源のカテゴリ")
    description: str = Field(..., description="地域資源の説明文")
    latitude: float = Field(..., description="地域資源の位置情報（緯度）")
    longitude: float = Field(..., description="地域資源の位置情報（経度）")
    file_base64: str | None = Field(
        default=None, description="添付ファイルのbase64エンコードされたバイト列"
    )
    content_type: str | None = Field(
        default=None, description="添付ファイルのMIMEタイプ"
    )


class ResourceRegistrationResponseBody(BaseModel):
    """`POST /resources`のレスポンスボディ。"""

    resource_id: str
    name: str
    category: str
    description: str
    latitude: float
    longitude: float
    file_url: str | None


class VacantPropertySearchRequestBody(BaseModel):
    """`POST /vacant-properties/search`のリクエストボディ。"""

    latitude: float = Field(..., description="検索基準位置の緯度")
    longitude: float = Field(..., description="検索基準位置の経度")
    radius_km: float = Field(..., description="検索半径（キロメートル）")
    business_status: BusinessStatus = Field(
        ...,
        description="絞り込み対象の営業状態"
        "（OPERATIONAL/CLOSED_TEMPORARILY/CLOSED_PERMANENTLY）",
    )
    types: list[str] | None = Field(
        default=None, description="業種・ジャンルタグによる絞り込み条件"
    )
    limit: int = Field(default=10, description="取得件数の上限")


class VacantPropertyBody(BaseModel):
    """居抜き物件候補1件分のボディ。"""

    place_id: str
    name: str
    latitude: float
    longitude: float
    business_status: BusinessStatus
    types: list[str]
    address: str | None
    phone_number: str | None
    estimated_closure_period_start: datetime | None
    estimated_closure_period_end: datetime | None


class VacantPropertySearchResponseBody(BaseModel):
    """`POST /vacant-properties/search`のレスポンスボディ。"""

    candidates: list[VacantPropertyBody]


# --------------------------------------------------------------------------
# エンドポイント
# --------------------------------------------------------------------------


@app.post("/consultations", response_model=ConsultationResponseBody)
def create_consultation(
    body: ConsultationRequestBody,
    resource_repository: ResourceRepository = Depends(get_resource_repository),
    inference_client: InferenceClient = Depends(get_inference_client),
) -> ConsultationResponseBody:
    """相談リクエストを受け付け、ハイブリッド検索+推論サービスによる

    回答生成を行う（Requirements 1.1, 1.2, 1.3, 1.5）。

    - 入力検証エラー（`query_text`空文字列、`radius_km<=0`、緯度経度の
      範囲外等）が発生した場合は400を返す
    - 推論サービス呼び出しが失敗した場合は502を返す
    """
    try:
        location = GeoPoint(latitude=body.latitude, longitude=body.longitude)
        request = ConsultationRequest(
            query_text=body.query_text,
            location=location,
            radius_km=body.radius_km,
            top_k=body.top_k,
        )
        response = generate_consultation_response(
            resource_repository, inference_client, request
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 推論サービス呼び出し失敗を502に変換する
        raise HTTPException(
            status_code=502, detail=f"推論サービスの呼び出しに失敗しました: {exc}"
        ) from exc

    return ConsultationResponseBody(
        generated_text=response.generated_text,
        referenced_resources=[
            RegionalResourceBody(
                resource_id=str(resource.resource_id),
                name=resource.name,
                category=resource.category,
                description=resource.description,
                latitude=resource.location.latitude,
                longitude=resource.location.longitude,
                file_url=resource.file_url,
            )
            for resource in response.referenced_resources
        ],
    )


@app.post(
    "/resources",
    response_model=ResourceRegistrationResponseBody,
    status_code=201,
)
def create_resource(
    body: ResourceRegistrationRequestBody,
    resource_repository: ResourceRepository = Depends(get_resource_repository),
    storage_client: StorageClient = Depends(get_storage_client),
) -> ResourceRegistrationResponseBody:
    """地域資源登録リクエストを受け付け、`register_resource()`を呼び出す

    （Requirements 5.1）。

    - 入力検証エラー（`name`/`category`/`description`の空文字列、
      緯度経度の範囲外、`file_base64`指定時の`content_type`未指定等）が
      発生した場合は400を返す
    - `file_base64`のbase64デコードに失敗した場合も400を返す
    - ストレージアップロード失敗時は503を返す
    """
    file_bytes: bytes | None = None
    if body.file_base64 is not None:
        try:
            file_bytes = base64.b64decode(body.file_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"file_base64のデコードに失敗しました: {exc}"
            ) from exc

    try:
        location = GeoPoint(latitude=body.latitude, longitude=body.longitude)
        resource = register_resource(
            resource_repository,
            storage_client,
            body.name,
            body.category,
            body.description,
            location,
            file_bytes,
            body.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - ストレージアップロード失敗を503に変換する
        raise HTTPException(
            status_code=503,
            detail=f"ファイルストレージへのアップロードに失敗しました: {exc}",
        ) from exc

    return ResourceRegistrationResponseBody(
        resource_id=str(resource.resource_id),
        name=resource.name,
        category=resource.category,
        description=resource.description,
        latitude=resource.location.latitude,
        longitude=resource.location.longitude,
        file_url=resource.file_url,
    )


@app.post(
    "/vacant-properties/search",
    response_model=VacantPropertySearchResponseBody,
)
async def search_vacant_properties_endpoint(
    body: VacantPropertySearchRequestBody,
    vacant_property_repository: VacantPropertyRepository = Depends(
        get_vacant_property_repository
    ),
    search_request_repository: SearchRequestRepository = Depends(
        get_search_request_repository
    ),
) -> VacantPropertySearchResponseBody:
    """居抜き物件検索リクエストを受け付け、`search_vacant_properties()`を

    呼び出す（Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6）。

    - 入力検証エラー（`radius_km<=0`、`limit<1`、緯度経度の範囲外等）が
      発生した場合は400を返す
    - その他の予期しない例外（DBエラー等）が発生した場合は500を返す
    - 検索が成功した場合、検索した場所・条件・結果件数を常に記録する
      （管理画面から「この場所でGoogle Places APIを検索する」機能のため）
    """
    try:
        location = GeoPoint(latitude=body.latitude, longitude=body.longitude)
        candidates = search_vacant_properties(
            vacant_property_repository,
            location,
            body.radius_km,
            body.business_status,
            body.types,
            body.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 予期しない例外（DBエラー等）を500に変換する
        raise HTTPException(
            status_code=500, detail=f"居抜き物件検索に失敗しました: {exc}"
        ) from exc

    try:
        await record_search_request(
            search_request_repository,
            location,
            body.radius_km,
            body.business_status,
            body.types,
            len(candidates),
        )
    except Exception:  # noqa: BLE001 - 履歴記録の失敗で検索応答自体を失敗させない
        logger.exception("検索リクエスト履歴の記録に失敗しました")

    return VacantPropertySearchResponseBody(
        candidates=[
            VacantPropertyBody(
                place_id=candidate.place_id,
                name=candidate.name,
                latitude=candidate.location.latitude,
                longitude=candidate.location.longitude,
                business_status=candidate.business_status,
                types=candidate.types,
                address=candidate.address,
                phone_number=candidate.phone_number,
                estimated_closure_period_start=candidate.estimated_closure_period_start,
                estimated_closure_period_end=candidate.estimated_closure_period_end,
            )
            for candidate in candidates
        ]
    )


# --------------------------------------------------------------------------
# 管理画面向けエンドポイント（/admin/*）
# --------------------------------------------------------------------------
# フロント画面(inuki)の/admin/配下の管理画面から呼び出される。
# ログイン以外の全エンドポイントは`Depends(get_current_admin_user)`により
# 有効なセッショントークン（Authorization: Bearer <token>）を要求する。


class AdminLoginRequestBody(BaseModel):
    """`POST /admin/auth/login`のリクエストボディ。"""

    username: str = Field(..., description="ログインID")
    password: str = Field(..., description="パスワード")


class AdminLoginResponseBody(BaseModel):
    """`POST /admin/auth/login`のレスポンスボディ。"""

    session_token: str
    display_name: str


class AdminUserBody(BaseModel):
    """管理ユーザー1件分のレスポンス表現（password_hashは含まない）。"""

    admin_user_id: str
    username: str
    display_name: str
    role: str
    is_active: bool


class AdminUserCreateRequestBody(BaseModel):
    """`POST /admin/users`のリクエストボディ。"""

    username: str = Field(..., description="ログインID")
    password: str = Field(..., description="パスワード（8文字以上）")
    display_name: str = Field(..., description="表示名")


class AdminUserUpdateRequestBody(BaseModel):
    """`PATCH /admin/users/{admin_user_id}`のリクエストボディ。

    指定しなかった項目（Noneのまま）は変更しない。
    """

    display_name: str | None = Field(default=None, description="表示名")
    password: str | None = Field(default=None, description="新しいパスワード（8文字以上）")
    is_active: bool | None = Field(default=None, description="有効/無効フラグ")


class DashboardSummaryBody(BaseModel):
    """`GET /admin/dashboard`のレスポンスボディ。"""

    regional_resource_count: int
    vacant_property_count: int
    consultation_log_count: int
    pending_update_request_count: int
    admin_user_count: int


class MunicipalityCountBody(BaseModel):
    """市町村別データ数の1件分。"""

    municipality: str
    count: int


class TypeCountBody(BaseModel):
    """業種別データ数の1件分。"""

    type_tag: str
    count: int


class VectorPointBody(BaseModel):
    """ベクトル分布散布図用の1点分。"""

    resource_id: str
    category: str
    x: float
    y: float


class ClusterCountBody(BaseModel):
    """カテゴリ別クラスタ数の1件分。"""

    category: str
    count: int


class StatsResponseBody(BaseModel):
    """`GET /admin/stats`のレスポンスボディ。"""

    municipality_counts_resources: list[MunicipalityCountBody]
    municipality_counts_vacant_properties: list[MunicipalityCountBody]
    type_counts: list[TypeCountBody]
    vector_points: list[VectorPointBody]
    cluster_counts: list[ClusterCountBody]


def _authorization_to_token(authorization: str | None) -> str:
    """`Authorization: Bearer <token>`ヘッダーからトークン文字列を取り出す。

    ヘッダーが無い、または形式が不正な場合は401を返す。
    """
    if authorization is None:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    return token


async def get_current_admin_user(
    authorization: str | None = Header(default=None),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> AdminUser:
    """`Authorization: Bearer <session_token>`ヘッダーから、ログイン中の

    管理ユーザーを解決する（`Depends`用）。無効・期限切れの場合は401を返す。
    """
    token = _authorization_to_token(authorization)
    try:
        return await resolve_session(admin_user_repository, token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _admin_user_to_body(user: AdminUser) -> AdminUserBody:
    return AdminUserBody(
        admin_user_id=str(user.admin_user_id),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
    )


@app.post("/admin/auth/login", response_model=AdminLoginResponseBody)
async def admin_login(
    body: AdminLoginRequestBody,
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> AdminLoginResponseBody:
    """管理ユーザーのユーザー名・パスワードによるログイン。

    成功時はセッショントークンを発行する。ユーザー名の存在有無を区別しない
    統一エラーメッセージで401を返す（列挙攻撃対策）。
    """
    try:
        session = await authenticate(admin_user_repository, body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await admin_user_repository.get_by_id(session.admin_user_id)
    assert user is not None  # authenticate直後のため必ず存在する
    return AdminLoginResponseBody(
        session_token=session.session_token, display_name=user.display_name
    )


@app.post("/admin/auth/logout", status_code=204, response_model=None)
async def admin_logout(
    authorization: str | None = Header(default=None),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> None:
    """現在のセッションを失効させる（ログアウト）。"""
    token = _authorization_to_token(authorization)
    await admin_user_repository.delete_session(token)


@app.get("/admin/auth/me", response_model=AdminUserBody)
async def admin_me(
    current_user: AdminUser = Depends(get_current_admin_user),
) -> AdminUserBody:
    """現在ログイン中の管理ユーザー情報を返す。"""
    return _admin_user_to_body(current_user)


@app.get("/admin/users", response_model=list[AdminUserBody])
async def admin_list_users(
    _current_user: AdminUser = Depends(get_current_admin_user),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> list[AdminUserBody]:
    """管理ユーザーの一覧を返す（管理ユーザー管理ページ用）。"""
    users = await admin_user_repository.list_all()
    return [_admin_user_to_body(user) for user in users]


@app.post("/admin/users", response_model=AdminUserBody, status_code=201)
async def admin_create_user(
    body: AdminUserCreateRequestBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> AdminUserBody:
    """新規管理ユーザーを作成する。"""
    try:
        user = await create_admin_user(
            admin_user_repository, body.username, body.password, body.display_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _admin_user_to_body(user)


@app.patch("/admin/users/{admin_user_id}", response_model=AdminUserBody)
async def admin_update_user(
    admin_user_id: str,
    body: AdminUserUpdateRequestBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> AdminUserBody:
    """管理ユーザーの表示名・パスワード・有効フラグを更新する。"""
    try:
        target_id = UUID(admin_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="admin_user_idの形式が不正です") from exc

    if body.password is not None and len(body.password) < 8:
        raise HTTPException(status_code=400, detail="パスワードは8文字以上である必要があります")

    existing = await admin_user_repository.get_by_id(target_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="管理ユーザーが見つかりません")
    if existing.username == "admin" and body.is_active is False:
        raise HTTPException(status_code=400, detail="初期管理者adminは無効化できません")

    from regional_revitalization.admin_auth import hash_password as _hash_password

    new_hash = _hash_password(body.password) if body.password is not None else None
    await admin_user_repository.update(
        target_id, body.display_name, new_hash, body.is_active
    )
    updated = await admin_user_repository.get_by_id(target_id)
    assert updated is not None
    return _admin_user_to_body(updated)


@app.delete("/admin/users/{admin_user_id}", status_code=204, response_model=None)
async def admin_delete_user(
    admin_user_id: str,
    current_user: AdminUser = Depends(get_current_admin_user),
    admin_user_repository: AdminUserRepository = Depends(get_admin_user_repository),
) -> None:
    """管理ユーザーを削除する。自分自身は削除できない（管理者ゼロ人化の防止）。"""
    try:
        target_id = UUID(admin_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="admin_user_idの形式が不正です") from exc

    if target_id == current_user.admin_user_id:
        raise HTTPException(status_code=400, detail="自分自身を削除することはできません")
    target = await admin_user_repository.get_by_id(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="管理ユーザーが見つかりません")
    if target.username == "admin":
        raise HTTPException(status_code=400, detail="初期管理者adminは削除できません")

    await admin_user_repository.delete(target_id)


@app.get("/admin/dashboard", response_model=DashboardSummaryBody)
async def admin_dashboard(
    _current_user: AdminUser = Depends(get_current_admin_user),
    admin_stats_repository: AdminStatsRepository = Depends(get_admin_stats_repository),
) -> DashboardSummaryBody:
    """ダッシュボードの概要統計（全体の状況）を返す。"""
    summary = await admin_stats_repository.get_dashboard_summary()
    return DashboardSummaryBody(
        regional_resource_count=summary.regional_resource_count,
        vacant_property_count=summary.vacant_property_count,
        consultation_log_count=summary.consultation_log_count,
        pending_update_request_count=summary.pending_update_request_count,
        admin_user_count=summary.admin_user_count,
    )


@app.get("/admin/stats", response_model=StatsResponseBody)
async def admin_stats(
    vector_points_limit: int = 500,
    _current_user: AdminUser = Depends(get_current_admin_user),
    admin_stats_repository: AdminStatsRepository = Depends(get_admin_stats_repository),
) -> StatsResponseBody:
    """統計情報ページ用の集計データ（市町村別・業種別・ベクトル分布）を返す。"""
    municipality_resources = await admin_stats_repository.get_municipality_counts_resources()
    municipality_vacant = (
        await admin_stats_repository.get_municipality_counts_vacant_properties()
    )
    type_counts = await admin_stats_repository.get_type_counts()
    vector_points = await admin_stats_repository.get_vector_points(vector_points_limit)
    cluster_counts = await admin_stats_repository.get_cluster_counts()

    return StatsResponseBody(
        municipality_counts_resources=[
            MunicipalityCountBody(municipality=m.municipality, count=m.count)
            for m in municipality_resources
        ],
        municipality_counts_vacant_properties=[
            MunicipalityCountBody(municipality=m.municipality, count=m.count)
            for m in municipality_vacant
        ],
        type_counts=[
            TypeCountBody(type_tag=t.type_tag, count=t.count) for t in type_counts
        ],
        vector_points=[
            VectorPointBody(
                resource_id=p.resource_id, category=p.category, x=p.x, y=p.y
            )
            for p in vector_points
        ],
        cluster_counts=[
            ClusterCountBody(category=c.category, count=c.count)
            for c in cluster_counts
        ],
    )


# --------------------------------------------------------------------------
# 管理画面向けエンドポイント（データ更新: /admin/resources/*）
# --------------------------------------------------------------------------
# マップから登録済みの地域資源を検索・編集・削除する機能。
# 全エンドポイントは有効なログインセッションを要求する。


class AdminResourceBody(BaseModel):
    """管理画面向けの地域資源1件分のレスポンス表現。"""

    resource_id: str
    name: str
    category: str
    description: str
    latitude: float
    longitude: float
    municipality: str
    file_url: str | None


class AdminResourceListResponseBody(BaseModel):
    """`GET /admin/resources`のレスポンスボディ。"""

    resources: list[AdminResourceBody]


class AdminResourceUpdateRequestBody(BaseModel):
    """`PATCH /admin/resources/{resource_id}`のリクエストボディ。

    指定しなかった項目（Noneのまま）は変更しない。
    """

    name: str | None = Field(default=None, description="名称")
    category: str | None = Field(default=None, description="カテゴリ")
    description: str | None = Field(default=None, description="説明文")
    latitude: float | None = Field(default=None, description="緯度")
    longitude: float | None = Field(default=None, description="経度")
    municipality: str | None = Field(default=None, description="市町村名")


def _resource_to_admin_body(resource: RegionalResource) -> AdminResourceBody:
    return AdminResourceBody(
        resource_id=str(resource.resource_id),
        name=resource.name,
        category=resource.category,
        description=resource.description,
        latitude=resource.location.latitude,
        longitude=resource.location.longitude,
        municipality=resource.municipality,
        file_url=resource.file_url,
    )


@app.get("/admin/resources", response_model=AdminResourceListResponseBody)
async def admin_list_resources(
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    limit: int = 200,
    _current_user: AdminUser = Depends(get_current_admin_user),
    resource_repository: ResourceRepository = Depends(get_resource_repository),
) -> AdminResourceListResponseBody:
    """管理画面のマップ表示用に、指定した矩形範囲内の地域資源一覧を返す。

    地図の現在の表示範囲（Leaflet等の`getBounds()`が返す
    南西端・北東端の緯度経度）をクエリパラメータとして渡す想定。
    """
    try:
        resources = search_resources_in_bounds(
            resource_repository,
            min_latitude,
            min_longitude,
            max_latitude,
            max_longitude,
            limit,
        )
        if inspect.isawaitable(resources):
            resources = await resources
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AdminResourceListResponseBody(
        resources=[_resource_to_admin_body(r) for r in resources]
    )


@app.patch("/admin/resources/{resource_id}", response_model=AdminResourceBody)
async def admin_update_resource(
    resource_id: str,
    body: AdminResourceUpdateRequestBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    resource_repository: ResourceRepository = Depends(get_resource_repository),
) -> AdminResourceBody:
    """地域資源の名称・カテゴリ・説明文・位置情報・市町村名を更新する。

    `latitude`/`longitude`はどちらか一方のみの指定は許可しない
    （両方指定または両方省略のいずれかとする）。
    """
    try:
        target_id = UUID(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="resource_idの形式が不正です") from exc

    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(
            status_code=400, detail="latitudeとlongitudeは両方指定するか両方省略してください"
        )
    location = (
        GeoPoint(latitude=body.latitude, longitude=body.longitude)
        if body.latitude is not None and body.longitude is not None
        else None
    )

    try:
        updated = update_resource(
            resource_repository,
            target_id,
            body.name,
            body.category,
            body.description,
            location,
            body.municipality,
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "見つかりません" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc

    return _resource_to_admin_body(updated)


@app.delete(
    "/admin/resources/{resource_id}", status_code=204, response_model=None
)
async def admin_delete_resource(
    resource_id: str,
    _current_user: AdminUser = Depends(get_current_admin_user),
    resource_repository: ResourceRepository = Depends(get_resource_repository),
) -> None:
    """地域資源を削除する。"""
    try:
        target_id = UUID(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="resource_idの形式が不正です") from exc

    try:
        delete_resource(resource_repository, target_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# 利用者からのデータ更新依頼（公開エンドポイント、認証不要）
# --------------------------------------------------------------------------
# 会員登録機能が無いため、依頼者情報は自由記述の連絡先文字列として受け取る。
# 申請自体はpendingとして保存されるだけで、regional_resourcesへの反映は
# 管理画面での承認操作時に初めて行われる（このエンドポイントは認証不要だが、
# データ改変は起こさない）。


class UpdateRequestSubmitBody(BaseModel):
    """`POST /update-requests`のリクエストボディ。"""

    target_resource_id: str | None = Field(
        default=None,
        description="変更提案の対象となる既存の地域資源ID。新規登録提案の場合はnull",
    )
    requester_contact: str | None = Field(default=None, description="依頼者の連絡先（任意）")
    requested_changes: dict = Field(
        ..., description="提案する変更内容（name/category/description/latitude/longitude/municipality）"
    )
    message: str | None = Field(default=None, description="依頼理由・補足メッセージ")


class UpdateRequestBody(BaseModel):
    """更新依頼1件分のレスポンス表現。"""

    request_id: str
    target_resource_id: str | None
    requester_contact: str | None
    requested_changes: dict
    message: str | None
    status: str
    reviewed_by_admin_id: str | None
    reviewed_at: datetime | None
    created_at: datetime


def _update_request_to_body(request: "UpdateRequest") -> UpdateRequestBody:
    return UpdateRequestBody(
        request_id=str(request.request_id),
        target_resource_id=(
            str(request.target_resource_id) if request.target_resource_id else None
        ),
        requester_contact=request.requester_contact,
        requested_changes=request.requested_changes,
        message=request.message,
        status=request.status,
        reviewed_by_admin_id=(
            str(request.reviewed_by_admin_id)
            if request.reviewed_by_admin_id
            else None
        ),
        reviewed_at=request.reviewed_at,
        created_at=request.created_at,
    )


@app.post("/update-requests", response_model=UpdateRequestBody, status_code=201)
async def create_update_request(
    body: UpdateRequestSubmitBody,
    update_request_repository: UpdateRequestRepository = Depends(
        get_update_request_repository
    ),
) -> UpdateRequestBody:
    """利用者からの地域資源データ更新依頼を受け付ける（認証不要の公開エンドポイント）。"""
    target_id: UUID | None = None
    if body.target_resource_id is not None:
        try:
            target_id = UUID(body.target_resource_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="target_resource_idの形式が不正です"
            ) from exc

    try:
        request = submit_update_request(
            target_id, body.requester_contact, body.requested_changes, body.message
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await update_request_repository.insert(request)
    return _update_request_to_body(request)


# --------------------------------------------------------------------------
# 管理画面向けエンドポイント（更新依頼の確認・承認・却下: /admin/update-requests/*）
# --------------------------------------------------------------------------


class UpdateRequestListResponseBody(BaseModel):
    """`GET /admin/update-requests`のレスポンスボディ。"""

    requests: list[UpdateRequestBody]


@app.get("/admin/update-requests", response_model=UpdateRequestListResponseBody)
async def admin_list_update_requests(
    status: str | None = None,
    _current_user: AdminUser = Depends(get_current_admin_user),
    update_request_repository: UpdateRequestRepository = Depends(
        get_update_request_repository
    ),
) -> UpdateRequestListResponseBody:
    """更新依頼の一覧を返す。`status`クエリパラメータで絞り込み可能

    （`pending`/`approved`/`rejected`のいずれか。省略時は全件）。
    """
    requests = await update_request_repository.list_by_status(status)
    return UpdateRequestListResponseBody(
        requests=[_update_request_to_body(r) for r in requests]
    )


@app.post(
    "/admin/update-requests/{request_id}/approve", response_model=AdminResourceBody
)
async def admin_approve_update_request(
    request_id: str,
    current_user: AdminUser = Depends(get_current_admin_user),
    update_request_repository: UpdateRequestRepository = Depends(
        get_update_request_repository
    ),
    resource_repository: ResourceRepository = Depends(get_resource_repository),
    storage_client: StorageClient = Depends(get_storage_client),
) -> AdminResourceBody:
    """更新依頼を承認し、地域資源データに反映する。"""
    try:
        target_id = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="request_idの形式が不正です") from exc

    try:
        result = await approve_request(
            update_request_repository,
            resource_repository,
            storage_client,
            target_id,
            current_user.admin_user_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "見つかりません" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return _resource_to_admin_body(result)


@app.post(
    "/admin/update-requests/{request_id}/reject",
    response_model=UpdateRequestBody,
)
async def admin_reject_update_request(
    request_id: str,
    current_user: AdminUser = Depends(get_current_admin_user),
    update_request_repository: UpdateRequestRepository = Depends(
        get_update_request_repository
    ),
) -> UpdateRequestBody:
    """更新依頼を却下する（地域資源データへの反映は行わない）。"""
    try:
        target_id = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="request_idの形式が不正です") from exc

    try:
        await reject_request(
            update_request_repository, target_id, current_user.admin_user_id
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "見つかりません" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    updated = await update_request_repository.get_by_id(target_id)
    assert updated is not None
    return _update_request_to_body(updated)


# --------------------------------------------------------------------------
# 管理画面向けエンドポイント（検索履歴・Places APIリアルタイム検索）
# --------------------------------------------------------------------------
# 利用者の居抜き物件検索リクエストは常に記録される（search_vacant_properties_
# endpoint参照）。管理画面はこの履歴一覧から、任意の1件を選んで
# 「この場所でGoogle Places APIを検索する」を実行できる。検索結果は
# 「登録待ち」の状態で保存され、管理者が個別に確認して登録するまでは
# vacant_property_candidatesへの反映は行われない。


class SearchRequestBody(BaseModel):
    """検索リクエスト履歴1件分のレスポンス表現。"""

    search_request_id: str
    latitude: float
    longitude: float
    radius_km: float
    business_status: str | None
    types: list[str] | None
    result_count: int
    created_at: datetime


class SearchRequestListResponseBody(BaseModel):
    """`GET /admin/search-requests`のレスポンスボディ。"""

    search_requests: list[SearchRequestBody]


class SearchOriginCreateBody(BaseModel):
    """管理画面の地図から登録するJOB検索起点。"""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TemplateRegisterResponseBody(BaseModel):
    template_group: str
    registered_count: int


def _search_request_to_body(request: SearchRequest) -> SearchRequestBody:
    return SearchRequestBody(
        search_request_id=str(request.search_request_id),
        latitude=request.location.latitude,
        longitude=request.location.longitude,
        radius_km=request.radius_km,
        business_status=(
            request.business_status.value if request.business_status else None
        ),
        types=request.types,
        result_count=request.result_count,
        created_at=request.created_at,
    )


@app.get("/admin/search-requests", response_model=SearchRequestListResponseBody)
async def admin_list_search_requests(
    limit: int = 100,
    _current_user: AdminUser = Depends(get_current_admin_user),
    search_request_repository: SearchRequestRepository = Depends(
        get_search_request_repository
    ),
) -> SearchRequestListResponseBody:
    """利用者の検索リクエスト履歴を直近順に返す。"""
    requests = await search_request_repository.list_recent(limit)
    return SearchRequestListResponseBody(
        search_requests=[_search_request_to_body(r) for r in requests]
    )


@app.post("/admin/search-origins", response_model=SearchRequestBody, status_code=201)
async def admin_create_search_origin(
    body: SearchOriginCreateBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    repository: SearchRequestRepository = Depends(get_search_request_repository),
) -> SearchRequestBody:
    """右クリック地点を10km圏の閉鎖店舗探索起点として登録する。"""
    request = await record_search_request(
        repository,
        location=GeoPoint(latitude=body.latitude, longitude=body.longitude),
        radius_km=10.0,
        business_status=BusinessStatus.CLOSED_PERMANENTLY,
        types=None,
        result_count=0,
    )
    return _search_request_to_body(request)


@app.get("/admin/search-origin-templates")
async def admin_list_search_origin_templates(
    _current_user: AdminUser = Depends(get_current_admin_user),
) -> dict[str, object]:
    stations = json.loads((Path.cwd() / "data/templates/stations.json").read_text(encoding="utf-8"))
    capitals = json.loads((Path.cwd() / "data/templates/prefectural_capitals.json").read_text(encoding="utf-8"))
    return {
        "station_groups": [
            {"name": name, "count": len(points)}
            for name, points in stations["groups"].items()
        ],
        "prefectural_capitals_count": len(capitals["points"]),
        "source": stations["source"],
    }


@app.post("/admin/search-origin-templates/{template_group}", response_model=TemplateRegisterResponseBody)
async def admin_register_search_origin_template(
    template_group: str,
    _current_user: AdminUser = Depends(get_current_admin_user),
    repository: SearchRequestRepository = Depends(get_search_request_repository),
) -> TemplateRegisterResponseBody:
    if template_group == "県庁所在地":
        data = json.loads((Path.cwd() / "data/templates/prefectural_capitals.json").read_text(encoding="utf-8"))
        points = data["points"]
    else:
        data = json.loads((Path.cwd() / "data/templates/stations.json").read_text(encoding="utf-8"))
        points = data["groups"].get(template_group)
        if points is None:
            raise HTTPException(status_code=404, detail="テンプレートが見つかりません")
    for point in points:
        await record_search_request(
            repository,
            location=GeoPoint(latitude=point["latitude"], longitude=point["longitude"]),
            radius_km=10.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            result_count=0,
        )
    return TemplateRegisterResponseBody(template_group=template_group, registered_count=len(points))


class PlacesSearchExecuteRequestBody(BaseModel):
    """`POST /admin/places-search`のリクエストボディ。"""

    search_request_id: str | None = Field(
        default=None, description="起点となる検索リクエスト履歴のID（任意）"
    )
    latitude: float = Field(..., description="検索基準位置の緯度")
    longitude: float = Field(..., description="検索基準位置の経度")
    radius_km: float = Field(..., description="検索半径（キロメートル）")
    keyword: str | None = Field(default=None, description="検索キーワード（任意）")


class PlacesSearchResultBody(BaseModel):
    """Places APIリアルタイム検索結果1件分のレスポンス表現。"""

    result_id: str
    place_id: str
    name: str
    latitude: float
    longitude: float
    business_status: str
    types: list[str]
    address: str | None
    phone_number: str | None
    is_registered: bool


class PlacesSearchExecuteResponseBody(BaseModel):
    """`POST /admin/places-search`のレスポンスボディ。"""

    results: list[PlacesSearchResultBody]


def _places_search_result_to_body(result: PlacesSearchResult) -> PlacesSearchResultBody:
    return PlacesSearchResultBody(
        result_id=str(result.result_id),
        place_id=result.place_id,
        name=result.name,
        latitude=result.location.latitude,
        longitude=result.location.longitude,
        business_status=result.business_status.value,
        types=result.types,
        address=result.address,
        phone_number=result.phone_number,
        is_registered=result.is_registered,
    )


@app.post("/admin/places-search", response_model=PlacesSearchExecuteResponseBody)
async def admin_execute_places_search(
    body: PlacesSearchExecuteRequestBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    places_search_client: PlacesSearchClient = Depends(get_places_search_client),
    places_search_result_repository: PlacesSearchResultRepository = Depends(
        get_places_search_result_repository
    ),
) -> PlacesSearchExecuteResponseBody:
    """指定した場所でGoogle Places APIのリアルタイム検索を実行する。

    検索履歴一覧のある行から「この場所で検索する」を押した場合は
    `search_request_id`を指定する。管理者が任意の場所を直接指定して
    検索することもできる（`search_request_id`は省略可）。

    結果は「登録待ち」の状態で保存されるのみで、`vacant_property_candidates`
    への反映は行われない（`POST /admin/places-search/{result_id}/register`
    で個別に登録する）。
    """
    search_request_id: UUID | None = None
    if body.search_request_id is not None:
        try:
            search_request_id = UUID(body.search_request_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="search_request_idの形式が不正です"
            ) from exc

    try:
        location = GeoPoint(latitude=body.latitude, longitude=body.longitude)
        results = await execute_places_search(
            places_search_client,
            places_search_result_repository,
            location,
            body.radius_km,
            body.keyword,
            search_request_id,
            BusinessStatus.CLOSED_PERMANENTLY,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PlacesApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PlacesSearchExecuteResponseBody(
        results=[_places_search_result_to_body(r) for r in results]
    )


@app.post(
    "/admin/places-search/{result_id}/register",
    response_model=PlacesSearchResultBody,
)
async def admin_register_places_search_result(
    result_id: str,
    _current_user: AdminUser = Depends(get_current_admin_user),
    places_search_result_repository: PlacesSearchResultRepository = Depends(
        get_places_search_result_repository
    ),
    vacant_property_repository: VacantPropertyRepository = Depends(
        get_vacant_property_repository
    ),
) -> PlacesSearchResultBody:
    """Places APIリアルタイム検索結果を、居抜き物件候補として正式に登録する。"""
    try:
        target_id = UUID(result_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="result_idの形式が不正です") from exc

    try:
        await register_search_result(
            places_search_result_repository, vacant_property_repository, target_id
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "見つかりません" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    updated = await places_search_result_repository.get_by_id(target_id)
    assert updated is not None
    return _places_search_result_to_body(updated)


# --------------------------------------------------------------------------
# 管理画面向けエンドポイント（居抜き物件候補のマップ表示・編集）
# --------------------------------------------------------------------------


class AdminVacantPropertyBody(BaseModel):
    """管理画面向けの居抜き物件候補1件分のレスポンス表現。"""

    place_id: str
    name: str
    latitude: float
    longitude: float
    business_status: str
    types: list[str]
    address: str | None
    phone_number: str | None
    rent_yen: int | None
    area_sqm: float | None
    built_year: int | None
    structure: str | None


class AdminVacantPropertyListResponseBody(BaseModel):
    """`GET /admin/vacant-properties`のレスポンスボディ。"""

    vacant_properties: list[AdminVacantPropertyBody]


class AdminVacantPropertyUpdateRequestBody(BaseModel):
    """`PATCH /admin/vacant-properties/{place_id}`のリクエストボディ。

    賃料・面積・築年数・構造は、いずれもGoogle Places APIからは取得できない
    管理画面専用の手動編集項目。`null`を指定すると値をクリアできる
    （他の更新系エンドポイントと異なり、指定しなかった項目のみを維持する
    COALESCE方式ではなく、送信された値で常に上書きする）。
    """

    rent_yen: int | None = Field(default=None, description="賃料（円/月）")
    area_sqm: float | None = Field(default=None, description="面積（平方メートル）")
    built_year: int | None = Field(default=None, description="築年")
    structure: str | None = Field(default=None, description="構造（例: 鉄骨造）")


def _vacant_property_to_admin_body(
    candidate: VacantPropertyCandidate,
) -> AdminVacantPropertyBody:
    return AdminVacantPropertyBody(
        place_id=candidate.place_id,
        name=candidate.name,
        latitude=candidate.location.latitude,
        longitude=candidate.location.longitude,
        business_status=candidate.business_status.value,
        types=candidate.types,
        address=candidate.address,
        phone_number=candidate.phone_number,
        rent_yen=candidate.rent_yen,
        area_sqm=candidate.area_sqm,
        built_year=candidate.built_year,
        structure=candidate.structure,
    )


@app.get(
    "/admin/vacant-properties", response_model=AdminVacantPropertyListResponseBody
)
async def admin_list_vacant_properties(
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    limit: int = 200,
    _current_user: AdminUser = Depends(get_current_admin_user),
    vacant_property_repository: VacantPropertyRepository = Depends(
        get_vacant_property_repository
    ),
) -> AdminVacantPropertyListResponseBody:
    """管理画面のマップ表示用に、指定した矩形範囲内の居抜き物件候補一覧を返す。"""
    try:
        candidates = search_vacant_properties_in_bounds(
            vacant_property_repository,
            min_latitude,
            min_longitude,
            max_latitude,
            max_longitude,
            limit,
        )
        if inspect.isawaitable(candidates):
            candidates = await candidates
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AdminVacantPropertyListResponseBody(
        vacant_properties=[_vacant_property_to_admin_body(c) for c in candidates]
    )


@app.patch(
    "/admin/vacant-properties/{place_id}", response_model=AdminVacantPropertyBody
)
async def admin_update_vacant_property(
    place_id: str,
    body: AdminVacantPropertyUpdateRequestBody,
    _current_user: AdminUser = Depends(get_current_admin_user),
    vacant_property_repository: VacantPropertyRepository = Depends(
        get_vacant_property_repository
    ),
) -> AdminVacantPropertyBody:
    """居抜き物件候補の賃料・面積・築年数・構造（管理画面専用の手動編集項目）を更新する。"""
    existing = vacant_property_repository.get_by_place_id(place_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"居抜き物件候補が見つかりません: {place_id}")

    try:
        update_vacant_property_details(
            vacant_property_repository,
            place_id,
            body.rent_yen,
            body.area_sqm,
            body.built_year,
            body.structure,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target = vacant_property_repository.get_by_place_id(place_id)
    assert target is not None
    return _vacant_property_to_admin_body(target)

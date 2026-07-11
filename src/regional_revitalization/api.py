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
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from regional_revitalization.consultation import generate_consultation_response
from regional_revitalization.inference import InferenceClient, MockInferenceClient
from regional_revitalization.models import ConsultationRequest, GeoPoint
from regional_revitalization.registration import register_resource
from regional_revitalization.repository import (
    InMemoryResourceRepository,
    ResourceRepository,
)
from regional_revitalization.storage import InMemoryStorageClient, StorageClient
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    VacantPropertyRepository,
    search_vacant_properties,
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
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
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


# --------------------------------------------------------------------------
# 起動時ブートストラップ（実運用実装への差し替え）
# --------------------------------------------------------------------------
# Cloud Run実行時は、環境変数`DATABASE_URL`・`GCS_BUCKET_NAME`が
# Terraform（Secret Manager経由）で設定されるため、それらが存在する場合のみ
# インメモリ実装からCloud SQL/Cloud Storage実装へ差し替える。
# 環境変数が未設定のローカル開発・単体テストではデフォルトのインメモリ実装の
# ままとし、実DB/実バケットへの接続を試行しない。
# 本関数は`_lifespan`（FastAPIのlifespanイベントハンドラ）から呼び出される。


async def _bootstrap_production_dependencies() -> None:
    """環境変数に応じて、共有インスタンスを実運用実装へ差し替える。"""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            import asyncpg

            from regional_revitalization.postgres_repository import (
                PostgresResourceRepository,
            )
            from regional_revitalization.postgres_vacant_property_repository import (
                PostgresVacantPropertyRepository,
            )

            pool = await asyncpg.create_pool(database_url)
            set_resource_repository(PostgresResourceRepository(pool))
            set_vacant_property_repository(
                PostgresVacantPropertyRepository(pool)
            )
            logger.info("Cloud SQL for PostgreSQLへの接続を初期化しました")
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

    inference_url = os.environ.get("INFERENCE_SERVICE_URL")
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
def search_vacant_properties_endpoint(
    body: VacantPropertySearchRequestBody,
    vacant_property_repository: VacantPropertyRepository = Depends(
        get_vacant_property_repository
    ),
) -> VacantPropertySearchResponseBody:
    """居抜き物件検索リクエストを受け付け、`search_vacant_properties()`を

    呼び出す（Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6）。

    - 入力検証エラー（`radius_km<=0`、`limit<1`、緯度経度の範囲外等）が
      発生した場合は400を返す
    - その他の予期しない例外（DBエラー等）が発生した場合は500を返す
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

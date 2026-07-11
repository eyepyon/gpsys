"""全体結合テスト（E2Eテスト）。

`design.md`のフロー1〜フロー4に対応するエンドツーエンドの流れを、
ローカルのモック構成（`fastapi.testclient.TestClient`とインメモリ実装）で検証する。

- フロー1: 相談応答（地域資源登録 → 相談リクエスト送信 → 参照資源・生成テキストの確認）
- フロー2: 地域資源登録（ファイル添付を含む登録 → resource_id/file_urlの発行確認）
- フロー3: 居抜き物件の同期・検知（`sync_vacant_properties()`によるCLOSED_PERMANENTLY検知
  からUPSERTまでの確認）
- フロー4: 居抜き物件の検索（同期済みデータに対する`search_vacant_properties()`/
  `POST /vacant-properties/search`エンドポイントの確認）

Validates: Requirements 1.1, 5.1, 11.1, 11.2, 11.3, 13.1, 13.2, 15.1
"""

from __future__ import annotations

import base64
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from regional_revitalization.api import (
    app,
    set_inference_client,
    set_resource_repository,
    set_storage_client,
    set_vacant_property_repository,
)
from regional_revitalization.inference import MockInferenceClient
from regional_revitalization.models import GeoPoint
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    MockPlacesApiClient,
    PlaceDetailsResult,
    search_vacant_properties,
    sync_vacant_properties,
)


@pytest.fixture(autouse=True)
def _reset_shared_instances() -> None:
    """各テスト前にアプリ本体サービスの共有インスタンスを

    デフォルト（インメモリ/モック実装）へリセットする。
    テスト間の状態汚染を防ぐため`autouse=True`とする。
    """
    set_resource_repository(InMemoryResourceRepository())
    set_storage_client(InMemoryStorageClient())
    set_inference_client(MockInferenceClient())
    set_vacant_property_repository(InMemoryVacantPropertyRepository())


@pytest.fixture()
def client() -> TestClient:
    """テスト用の`TestClient`を返す。"""
    return TestClient(app)


class TestFlow1ConsultationEndToEnd:
    """フロー1（相談応答）のE2Eテスト。

    `POST /resources`で地域資源を登録した後、`POST /consultations`で
    相談リクエストを送信し、登録した資源が`referenced_resources`に
    含まれ、`generated_text`が返ることを確認する。

    Validates: Requirements 1.1, 5.1
    """

    def test_資源登録後の相談で登録資源が参照され生成テキストが返る(
        self, client: TestClient
    ) -> None:
        """地域資源登録 → 相談リクエスト送信のE2Eフローを検証する。"""
        # Step 1: 地域資源を登録する（フロー2の前半部分を利用）
        registration_payload = {
            "name": "道の駅 湖畔の郷",
            "category": "観光施設",
            "description": "子育て世帯向けの支援制度に関する相談窓口を併設した施設。",
            "latitude": 35.4,
            "longitude": 138.9,
        }
        registration_response = client.post("/resources", json=registration_payload)
        assert registration_response.status_code == 201
        registered_resource_id = registration_response.json()["resource_id"]

        # Step 2: 登録した資源の近隣・関連する相談リクエストを送信する
        consultation_payload = {
            "query_text": "子育て世帯向けの支援制度を知りたい",
            "latitude": 35.4,
            "longitude": 138.9,
            "radius_km": 10.0,
            "top_k": 5,
        }
        consultation_response = client.post(
            "/consultations", json=consultation_payload
        )

        assert consultation_response.status_code == 200
        body = consultation_response.json()
        # 生成テキストが返ること（Requirements 1.4）
        assert body["generated_text"] != ""
        # 登録した資源が参照資源一覧に含まれること
        referenced_ids = [
            resource["resource_id"] for resource in body["referenced_resources"]
        ]
        assert registered_resource_id in referenced_ids


class TestFlow2ResourceRegistrationEndToEnd:
    """フロー2（地域資源登録、ファイル添付含む）のE2Eテスト。

    `POST /resources`でファイル添付を含む地域資源登録を行い、
    `resource_id`・`file_url`が正しく発行されることを確認する。

    Validates: Requirements 5.1
    """

    def test_ファイル添付を含む登録でresource_idとfile_urlが発行される(
        self, client: TestClient
    ) -> None:
        """ファイル添付を含む地域資源登録のE2Eフローを検証する。"""
        file_content = b"%PDF-1.4 dummy brochure content"
        payload = {
            "name": "空き家活用支援センター",
            "category": "支援制度",
            "description": "空き家の活用に関する相談・マッチング支援を行う。",
            "latitude": 35.6,
            "longitude": 139.7,
            "file_base64": base64.b64encode(file_content).decode("ascii"),
            "content_type": "application/pdf",
        }

        response = client.post("/resources", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["resource_id"] != ""
        assert body["file_url"] is not None
        assert body["file_url"].startswith("https://")


class TestFlow3VacantPropertySyncEndToEnd:
    """フロー3（居抜き物件の同期・検知）のE2Eテスト。

    `sync_vacant_properties()`（`MockPlacesApiClient`使用）で
    `CLOSED_PERMANENTLY`を検知させ、`InMemoryVacantPropertyRepository`に
    UPSERTされることを確認する。
    `POST /vacant-properties/search`エンドポイント経由での取得確認も行う。

    Validates: Requirements 13.1, 13.2, 15.1
    """

    def test_closed_permanently検知からUPSERTと検索APIでの取得までを確認する(
        self, client: TestClient
    ) -> None:
        """`sync_vacant_properties()`によるUPSERTと、検索APIでの取得を検証する。"""
        # Step 1: CLOSED_PERMANENTLYのスポットを含むPlaces APIのモックを用意する
        target_place_id = "ChIJ_e2e_test_place_1"
        places_api_client = MockPlacesApiClient(
            details_by_place_id={
                target_place_id: PlaceDetailsResult(
                    place_id=target_place_id,
                    name="旧たなか食堂",
                    location=GeoPoint(latitude=35.4, longitude=138.9),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["restaurant"],
                    address="山梨県某市1-2-3",
                    phone_number="055-111-2222",
                    latest_review_time=datetime(2024, 1, 1),
                ),
            }
        )
        vacant_property_repository = InMemoryVacantPropertyRepository()

        # Step 2: 同期処理を実行し、CLOSED_PERMANENTLYが検知されUPSERTされることを確認する
        sync_result = sync_vacant_properties(
            places_api_client, vacant_property_repository, [target_place_id]
        )

        assert sync_result.processed_count == 1
        assert sync_result.detected_closure_count == 1
        assert sync_result.error_count == 0
        assert len(vacant_property_repository) == 1

        # Step 3: 同期結果をアプリ本体サービスの共有リポジトリへ差し替え、
        # 検索APIエンドポイント経由でも取得できることを確認する
        set_vacant_property_repository(vacant_property_repository)
        search_payload = {
            "latitude": 35.4,
            "longitude": 138.9,
            "radius_km": 5.0,
            "business_status": "CLOSED_PERMANENTLY",
        }
        search_response = client.post(
            "/vacant-properties/search", json=search_payload
        )

        assert search_response.status_code == 200
        candidates = search_response.json()["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["place_id"] == target_place_id
        assert candidates[0]["name"] == "旧たなか食堂"

    def test_同一place_idで複数回同期しても1件のみに保たれる(self) -> None:
        """同一`place_id`について同期処理を複数回実行しても、

        UPSERTにより該当レコードが常に1件のみであることを確認する
        （Requirements 13.2）。
        """
        target_place_id = "ChIJ_e2e_test_place_upsert"
        places_api_client = MockPlacesApiClient(
            details_by_place_id={
                target_place_id: PlaceDetailsResult(
                    place_id=target_place_id,
                    name="旧やまだ商店",
                    location=GeoPoint(latitude=35.1, longitude=138.5),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["store"],
                    address=None,
                    phone_number=None,
                    latest_review_time=None,
                ),
            }
        )
        vacant_property_repository = InMemoryVacantPropertyRepository()

        sync_vacant_properties(
            places_api_client, vacant_property_repository, [target_place_id]
        )
        sync_vacant_properties(
            places_api_client, vacant_property_repository, [target_place_id]
        )

        assert len(vacant_property_repository) == 1


class TestFlow4VacantPropertySearchEndToEnd:
    """フロー4（居抜き物件の検索）のE2Eテスト。

    同期で登録済みの居抜き物件候補に対して`POST /vacant-properties/search`を
    呼び出し、期待する候補が返ることを確認する。

    Validates: Requirements 15.1
    """

    def test_同期済み候補への位置業種条件検索で期待する候補が返る(
        self, client: TestClient
    ) -> None:
        """同期済みの複数候補に対する位置・業種による絞り込み検索を検証する。"""
        # Step 1: 複数のCLOSED_PERMANENTLYスポットを同期する
        places_api_client = MockPlacesApiClient(
            details_by_place_id={
                "place-restaurant": PlaceDetailsResult(
                    place_id="place-restaurant",
                    name="旧洋食店リコ",
                    location=GeoPoint(latitude=35.40, longitude=138.90),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["restaurant", "cafe"],
                    address="山梨県某市2-1",
                    phone_number=None,
                    latest_review_time=datetime(2024, 2, 1),
                ),
                "place-far-away": PlaceDetailsResult(
                    place_id="place-far-away",
                    name="遠方の廃業店舗",
                    location=GeoPoint(latitude=40.0, longitude=140.0),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["restaurant"],
                    address=None,
                    phone_number=None,
                    latest_review_time=None,
                ),
                "place-operational": PlaceDetailsResult(
                    place_id="place-operational",
                    name="営業中の店舗",
                    location=GeoPoint(latitude=35.41, longitude=138.91),
                    business_status=BusinessStatus.OPERATIONAL,
                    types=["restaurant"],
                    address=None,
                    phone_number=None,
                    latest_review_time=None,
                ),
            }
        )
        vacant_property_repository = InMemoryVacantPropertyRepository()
        sync_result = sync_vacant_properties(
            places_api_client,
            vacant_property_repository,
            ["place-restaurant", "place-far-away", "place-operational"],
        )
        # 営業中の店舗はCLOSED_PERMANENTLYではないため検知対象外
        assert sync_result.detected_closure_count == 2

        set_vacant_property_repository(vacant_property_repository)

        # Step 2: 近隣かつ業種タグ"restaurant"に合致する候補を検索する
        search_payload = {
            "latitude": 35.40,
            "longitude": 138.90,
            "radius_km": 10.0,
            "business_status": "CLOSED_PERMANENTLY",
            "types": ["restaurant"],
        }
        response = client.post("/vacant-properties/search", json=search_payload)

        assert response.status_code == 200
        candidates = response.json()["candidates"]
        # 近隣の"place-restaurant"のみが返り、遠方の"place-far-away"は除外される
        assert len(candidates) == 1
        assert candidates[0]["place_id"] == "place-restaurant"

    def test_関数呼び出しでも直接検索できる(self) -> None:
        """`search_vacant_properties()`関数を直接呼び出した場合も

        同様の結果が得られることを確認する。
        """
        places_api_client = MockPlacesApiClient(
            details_by_place_id={
                "place-direct": PlaceDetailsResult(
                    place_id="place-direct",
                    name="旧直接呼び出しテスト店舗",
                    location=GeoPoint(latitude=35.0, longitude=135.0),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["cafe"],
                    address=None,
                    phone_number=None,
                    latest_review_time=datetime(2024, 3, 1),
                ),
            }
        )
        vacant_property_repository = InMemoryVacantPropertyRepository()
        sync_vacant_properties(
            places_api_client, vacant_property_repository, ["place-direct"]
        )

        results = search_vacant_properties(
            vacant_property_repository,
            GeoPoint(latitude=35.0, longitude=135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=["cafe"],
            limit=10,
        )

        assert len(results) == 1
        assert results[0].place_id == "place-direct"

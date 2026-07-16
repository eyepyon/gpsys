"""アプリ本体サービス（FastAPI）のAPIエンドポイントの単体テスト。

`fastapi.testclient.TestClient`（httpxベース）を用いて、
`POST /consultations`, `POST /resources`の正常系・異常系（ステータスコード）
を検証する。

Validates: Requirements 1.1, 1.2, 1.3, 1.5, 5.1
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from datetime import datetime

from regional_revitalization.api import (
    app,
    set_inference_client,
    set_resource_repository,
    set_storage_client,
    set_vacant_property_repository,
)
from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    VacantPropertyCandidate,
)


@pytest.fixture(autouse=True)
def _reset_shared_instances() -> None:
    """各テスト前に共有インスタンスをデフォルト（インメモリ/モック）へ

    リセットする。テスト間の状態汚染を防ぐため`autouse=True`とする。
    """
    from regional_revitalization.inference import MockInferenceClient

    set_resource_repository(InMemoryResourceRepository())
    set_storage_client(InMemoryStorageClient())
    set_inference_client(MockInferenceClient())
    set_vacant_property_repository(InMemoryVacantPropertyRepository())


@pytest.fixture()
def client() -> TestClient:
    """テスト用の`TestClient`を返す。"""
    return TestClient(app)


class TestCreateConsultation:
    """`POST /consultations`エンドポイントのテスト。

    Validates: Requirements 1.1, 1.2, 1.3, 1.5
    """

    def _valid_payload(self) -> dict:
        return {
            "query_text": "子育て世帯向けの支援制度を知りたい",
            "latitude": 35.4,
            "longitude": 138.9,
            "radius_km": 10.0,
        }

    def test_正常系で200を返し生成テキストと参照資源を含む(
        self, client: TestClient
    ) -> None:
        """有効な相談リクエストに対して200と`generated_text`,

        `referenced_resources`を返すことを確認する（Requirements 1.1, 1.4）。
        """
        response = client.post("/consultations", json=self._valid_payload())

        assert response.status_code == 200
        body = response.json()
        assert "generated_text" in body
        assert body["generated_text"] != ""
        assert "referenced_resources" in body
        assert isinstance(body["referenced_resources"], list)

    def test_query_textが空文字列の場合400を返す(self, client: TestClient) -> None:
        """`query_text`が空文字列の場合に400が返ることを確認する

        （Requirements 1.2）。
        """
        payload = self._valid_payload()
        payload["query_text"] = ""

        response = client.post("/consultations", json=payload)

        assert response.status_code == 400

    @pytest.mark.parametrize("radius_km", [0.0, -1.0, -5.0])
    def test_radius_kmが0以下の場合400を返す(
        self, client: TestClient, radius_km: float
    ) -> None:
        """`radius_km`が0以下の場合に400が返ることを確認する

        （Requirements 1.3）。
        """
        payload = self._valid_payload()
        payload["radius_km"] = radius_km

        response = client.post("/consultations", json=payload)

        assert response.status_code == 400

    def test_緯度が範囲外の場合400を返す(self, client: TestClient) -> None:
        """緯度が-90~90の範囲外の場合に400が返ることを確認する

        （Requirements 6.1, 6.3）。
        """
        payload = self._valid_payload()
        payload["latitude"] = 999.0

        response = client.post("/consultations", json=payload)

        assert response.status_code == 400

    def test_推論サービス呼び出し失敗時に502を返す(self, client: TestClient) -> None:
        """推論サービスの呼び出しが失敗した場合に502が返ることを確認する

        （Requirements 1.5）。
        """

        class RaisingInferenceClient:
            """`generate()`呼び出し時に必ず例外を発生させるモック実装。"""

            def generate(
                self, query_text: str, context: list[RegionalResource]
            ) -> str:
                raise ConnectionError("推論サービスへの接続に失敗しました")

        set_inference_client(RaisingInferenceClient())

        response = client.post("/consultations", json=self._valid_payload())

        assert response.status_code == 502


class TestCreateResource:
    """`POST /resources`エンドポイントのテスト。

    Validates: Requirements 5.1
    """

    def _valid_payload(self) -> dict:
        return {
            "name": "道の駅 湖畔の郷",
            "category": "観光施設",
            "description": "地元産の農産物直売所と休憩施設。",
            "latitude": 35.4,
            "longitude": 138.9,
        }

    def test_正常系で201を返しresource_idとfile_urlを含む(
        self, client: TestClient
    ) -> None:
        """有効な登録リクエストに対して201と`resource_id`,

        `file_url`（Noneのまま）を返すことを確認する
        （Requirements 5.1, 5.3）。
        """
        response = client.post("/resources", json=self._valid_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["resource_id"]
        assert body["file_url"] is None

    def test_添付ファイル指定時にfile_urlが設定される(
        self, client: TestClient
    ) -> None:
        """`file_base64`と`content_type`を指定した場合に

        `file_url`が非Noneで返ることを確認する（Requirements 5.2）。
        """
        payload = self._valid_payload()
        payload["file_base64"] = base64.b64encode(b"dummy-file-content").decode(
            "ascii"
        )
        payload["content_type"] = "application/pdf"

        response = client.post("/resources", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["file_url"] is not None

    def test_nameが空文字列の場合400を返す(self, client: TestClient) -> None:
        """`name`が空文字列の場合に400が返ることを確認する

        （Requirements 5.6）。
        """
        payload = self._valid_payload()
        payload["name"] = ""

        response = client.post("/resources", json=payload)

        assert response.status_code == 400

    def test_categoryが空文字列の場合400を返す(self, client: TestClient) -> None:
        """`category`が空文字列の場合に400が返ることを確認する

        （Requirements 5.6）。
        """
        payload = self._valid_payload()
        payload["category"] = ""

        response = client.post("/resources", json=payload)

        assert response.status_code == 400

    def test_file_base64指定時にcontent_type未指定だと400を返す(
        self, client: TestClient
    ) -> None:
        """`file_base64`が指定されているが`content_type`が

        未指定の場合に400が返ることを確認する（Requirements 5.8）。
        """
        payload = self._valid_payload()
        payload["file_base64"] = base64.b64encode(b"dummy-file-content").decode(
            "ascii"
        )

        response = client.post("/resources", json=payload)

        assert response.status_code == 400

    def test_緯度が範囲外の場合400を返す(self, client: TestClient) -> None:
        """緯度が-90~90の範囲外の場合に400が返ることを確認する

        （Requirements 5.7）。
        """
        payload = self._valid_payload()
        payload["latitude"] = -999.0

        response = client.post("/resources", json=payload)

        assert response.status_code == 400

    def test_ストレージアップロード失敗時に503を返す(self, client: TestClient) -> None:
        """ストレージアップロードが失敗した場合に503が返ることを確認する

        （Requirements 5.4）。
        """

        class RaisingStorageClient:
            """`upload()`呼び出し時に必ず例外を発生させるモック実装。"""

            def upload(
                self, file_bytes: bytes, object_name: str, content_type: str
            ) -> str:
                raise ConnectionError("Cloud Storageへのアップロードに失敗しました")

        set_storage_client(RaisingStorageClient())
        payload = self._valid_payload()
        payload["file_base64"] = base64.b64encode(b"dummy-file-content").decode(
            "ascii"
        )
        payload["content_type"] = "application/pdf"

        response = client.post("/resources", json=payload)

        assert response.status_code == 503


class TestSearchVacantProperties:
    """`POST /vacant-properties/search`エンドポイントのテスト。

    Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
    """

    def _valid_payload(self) -> dict:
        return {
            "latitude": 35.4,
            "longitude": 138.9,
            "radius_km": 10.0,
            "business_status": "CLOSED_PERMANENTLY",
        }

    def _make_candidate(
        self,
        place_id: str = "place-1",
        latitude: float = 35.4,
        longitude: float = 138.9,
        business_status: BusinessStatus = BusinessStatus.CLOSED_PERMANENTLY,
    ) -> VacantPropertyCandidate:
        return VacantPropertyCandidate(
            place_id=place_id,
            name="旧店舗",
            location=GeoPoint(latitude=latitude, longitude=longitude),
            business_status=business_status,
            types=["restaurant"],
            address="山梨県某市1-1",
            phone_number="055-000-0000",
            data_fetched_at=datetime(2024, 1, 10),
            last_review_time=datetime(2024, 1, 1),
            estimated_closure_period_start=datetime(2024, 1, 1),
            estimated_closure_period_end=datetime(2024, 1, 10),
        )

    def test_正常系で200を返し候補一覧を含む(self, client: TestClient) -> None:
        """有効な検索リクエストに対して200と`candidates`を

        返すことを確認する（Requirements 15.1, 15.2, 15.3）。
        """
        set_vacant_property_repository(
            InMemoryVacantPropertyRepository([self._make_candidate()])
        )

        response = client.post(
            "/vacant-properties/search", json=self._valid_payload()
        )

        assert response.status_code == 200
        body = response.json()
        assert "candidates" in body
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["place_id"] == "place-1"

    def test_business_status未指定時は営業状態で絞り込まない(
        self, client: TestClient
    ) -> None:
        candidates = [
            self._make_candidate("closed"),
            self._make_candidate("open", business_status=BusinessStatus.OPERATIONAL),
        ]
        set_vacant_property_repository(InMemoryVacantPropertyRepository(candidates))
        payload = self._valid_payload()
        payload.pop("business_status")

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 200
        assert {item["place_id"] for item in response.json()["candidates"]} == {
            "closed",
            "open",
        }

    @pytest.mark.parametrize("radius_km", [0.0, -1.0, -5.0])
    def test_radius_kmが0以下の場合400を返す(
        self, client: TestClient, radius_km: float
    ) -> None:
        """`radius_km`が0以下の場合に400が返ることを確認する

        （Requirements 15.1）。
        """
        payload = self._valid_payload()
        payload["radius_km"] = radius_km

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 400

    def test_limitが1未満の場合400を返す(self, client: TestClient) -> None:
        """`limit`が1未満の場合に400が返ることを確認する

        （Requirements 15.1）。
        """
        payload = self._valid_payload()
        payload["limit"] = 0

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 400

    def test_緯度が範囲外の場合400を返す(self, client: TestClient) -> None:
        """緯度が-90~90の範囲外の場合に400が返ることを確認する

        （Requirements 15.1）。
        """
        payload = self._valid_payload()
        payload["latitude"] = 999.0

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 400

    def test_経度が範囲外の場合400を返す(self, client: TestClient) -> None:
        """経度が-180~180の範囲外の場合に400が返ることを確認する

        （Requirements 15.1）。
        """
        payload = self._valid_payload()
        payload["longitude"] = -999.0

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 400

    def test_business_statusが不正な値の場合422を返す(
        self, client: TestClient
    ) -> None:
        """`business_status`がEnumに存在しない値の場合に

        FastAPI/Pydanticの標準検証により422が返ることを確認する
        （Requirements 15.3）。
        """
        payload = self._valid_payload()
        payload["business_status"] = "INVALID_STATUS"

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 422

    def test_typesを指定して積集合が無い候補は除外される(
        self, client: TestClient
    ) -> None:
        """`types`を指定した場合、積集合が空の候補が除外され

        200が返ることを確認する（Requirements 15.4）。
        """
        set_vacant_property_repository(
            InMemoryVacantPropertyRepository([self._make_candidate()])
        )
        payload = self._valid_payload()
        payload["types"] = ["cafe"]

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 200
        assert response.json()["candidates"] == []

    def test_limitで件数が制限される(self, client: TestClient) -> None:
        """候補件数が`limit`を超える場合に戻り値が`limit`件以下に

        制限されることを確認する（Requirements 15.5）。
        """
        candidates = [
            self._make_candidate(place_id=f"place-{i}") for i in range(3)
        ]
        set_vacant_property_repository(InMemoryVacantPropertyRepository(candidates))
        payload = self._valid_payload()
        payload["limit"] = 2

        response = client.post("/vacant-properties/search", json=payload)

        assert response.status_code == 200
        assert len(response.json()["candidates"]) == 2

    def test_リポジトリ例外時に500を返す(self, client: TestClient) -> None:
        """リポジトリ呼び出し（DB相当）が予期しない例外を発生させた場合に

        500が返ることを確認する（Requirements 15.6）。
        """

        class RaisingVacantPropertyRepository:
            """`search_by_business_status_and_type()`呼び出し時に

            必ず例外を発生させるモック実装。
            """

            def upsert_by_place_id(self, candidate: VacantPropertyCandidate) -> None:
                raise NotImplementedError

            def search_by_business_status_and_type(
                self,
                location: GeoPoint,
                radius_km: float,
                business_status: BusinessStatus,
                types: list[str] | None,
                limit: int,
            ) -> list[VacantPropertyCandidate]:
                raise ConnectionError("データベースへの接続に失敗しました")

        set_vacant_property_repository(RaisingVacantPropertyRepository())

        response = client.post(
            "/vacant-properties/search", json=self._valid_payload()
        )

        assert response.status_code == 500

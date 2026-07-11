"""居抜き物件同期サービス（Cloud Run Jobs）エントリポイントの単体テスト。

環境変数読み込みロジック（`parse_target_place_ids`, `parse_db_connection_json`,
`get_places_api_key`, `load_config_from_env`）が正しく解析されること、および
必須環境変数が欠けている場合に`ConfigurationError`が発生することを検証する。
実際のDB/Places API呼び出しはモック化する。

Validates: Requirements 13.5, 13.6
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from regional_revitalization.models import GeoPoint
from regional_revitalization.vacant_property import (
    BusinessStatus,
    PlaceDetailsResult,
    PlacesApiError,
    SyncResult,
)
from regional_revitalization.vacant_property_sync_job import (
    ConfigurationError,
    JobConfig,
    build_dsn,
    get_places_api_key,
    load_config_from_env,
    parse_db_connection_json,
    parse_target_place_ids,
    run_sync_job,
)

_VALID_DB_CONNECTION = {
    "host": "10.0.0.1",
    "port": 5432,
    "database": "app_db",
    "user": "app_user",
    "password": "secret-password",  # noqa: S105 - テスト用の固定値
}


@pytest.fixture(autouse=True)
def _reset_environment() -> None:
    """各テスト前後で関連する環境変数をクリーンな状態に保つ。"""
    keys = (
        "DB_CONNECTION_JSON",
        "PLACES_API_KEY",
        "PLACES_API_KEY_SECRET_NAME",
        "GCP_PROJECT_ID",
        "TARGET_PLACE_IDS",
    )
    for key in keys:
        os_environ_pop(key)
    yield
    for key in keys:
        os_environ_pop(key)


def os_environ_pop(key: str) -> None:
    """テスト用のヘルパー: 環境変数を安全に削除する。"""
    import os

    os.environ.pop(key, None)


def _set_env(**kwargs: str) -> None:
    """テスト用のヘルパー: 複数の環境変数を一括設定する。"""
    import os

    for key, value in kwargs.items():
        os.environ[key] = value


class TestParseTargetPlaceIds:
    """`parse_target_place_ids()`のテスト。"""

    def test_カンマ区切り文字列を正しくリストへ変換する(self) -> None:
        result = parse_target_place_ids("place_1,place_2,place_3")
        assert result == ["place_1", "place_2", "place_3"]

    def test_前後の空白を除去する(self) -> None:
        result = parse_target_place_ids(" place_1 , place_2 ")
        assert result == ["place_1", "place_2"]

    def test_空要素は無視される(self) -> None:
        result = parse_target_place_ids("place_1,,place_2,")
        assert result == ["place_1", "place_2"]

    def test_単一のplace_idも解析できる(self) -> None:
        result = parse_target_place_ids("place_1")
        assert result == ["place_1"]

    def test_有効な要素が1件も無い場合は設定エラーになる(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_target_place_ids("")

    def test_カンマのみの場合も設定エラーになる(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_target_place_ids(" , , ")


class TestParseDbConnectionJson:
    """`parse_db_connection_json()`のテスト。"""

    def test_正常なjsonを辞書へ変換する(self) -> None:
        raw = json.dumps(_VALID_DB_CONNECTION)
        result = parse_db_connection_json(raw)
        assert result == _VALID_DB_CONNECTION

    def test_不正なjson文字列は設定エラーになる(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_db_connection_json("{not a valid json")

    def test_json配列は設定エラーになる(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_db_connection_json("[1, 2, 3]")

    @pytest.mark.parametrize(
        "missing_key", ["host", "port", "database", "user", "password"]
    )
    def test_必須キーが欠けている場合は設定エラーになる(
        self, missing_key: str
    ) -> None:
        data = dict(_VALID_DB_CONNECTION)
        del data[missing_key]
        with pytest.raises(ConfigurationError):
            parse_db_connection_json(json.dumps(data))


class TestGetPlacesApiKey:
    """`get_places_api_key()`のテスト。"""

    def test_places_api_key環境変数が優先的に使用される(self) -> None:
        _set_env(PLACES_API_KEY="direct-api-key")
        assert get_places_api_key() == "direct-api-key"

    def test_places_api_key未設定かつsecret_name未設定の場合は設定エラーになる(
        self,
    ) -> None:
        with pytest.raises(ConfigurationError):
            get_places_api_key()

    def test_secret_manager経由の取得はモック化して検証する(self) -> None:
        """`PLACES_API_KEY_SECRET_NAME`指定時にSecret Managerクライアントの

        `access_secret_version()`が呼び出され、その戻り値からAPIキーを
        取得できることを確認する。
        """
        _set_env(
            PLACES_API_KEY_SECRET_NAME=(
                "projects/test-project/secrets/places-key/versions/latest"
            )
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.payload.data = b"secret-manager-api-key"
        mock_client.access_secret_version.return_value = mock_response

        mock_secretmanager_module = MagicMock()
        mock_secretmanager_module.SecretManagerServiceClient.return_value = (
            mock_client
        )

        import sys

        original_module = sys.modules.get("google.cloud.secretmanager")
        sys.modules["google.cloud.secretmanager"] = mock_secretmanager_module
        try:
            result = get_places_api_key()
        finally:
            if original_module is not None:
                sys.modules["google.cloud.secretmanager"] = original_module
            else:
                sys.modules.pop("google.cloud.secretmanager", None)

        assert result == "secret-manager-api-key"
        mock_client.access_secret_version.assert_called_once_with(
            name="projects/test-project/secrets/places-key/versions/latest"
        )


class TestLoadConfigFromEnv:
    """`load_config_from_env()`のテスト。"""

    def test_すべての環境変数が設定されている場合正しく設定値を組み立てる(
        self,
    ) -> None:
        _set_env(
            DB_CONNECTION_JSON=json.dumps(_VALID_DB_CONNECTION),
            PLACES_API_KEY="direct-api-key",
            GCP_PROJECT_ID="test-project",
            TARGET_PLACE_IDS="place_1,place_2",
        )

        config = load_config_from_env()

        assert config == JobConfig(
            db_connection=_VALID_DB_CONNECTION,
            places_api_key="direct-api-key",
            gcp_project_id="test-project",
            target_place_ids=["place_1", "place_2"],
        )

    def test_db_connection_json未設定の場合は設定エラーになる(self) -> None:
        _set_env(
            PLACES_API_KEY="direct-api-key",
            GCP_PROJECT_ID="test-project",
            TARGET_PLACE_IDS="place_1",
        )
        with pytest.raises(ConfigurationError):
            load_config_from_env()

    def test_gcp_project_id未設定の場合は設定エラーになる(self) -> None:
        _set_env(
            DB_CONNECTION_JSON=json.dumps(_VALID_DB_CONNECTION),
            PLACES_API_KEY="direct-api-key",
            TARGET_PLACE_IDS="place_1",
        )
        with pytest.raises(ConfigurationError):
            load_config_from_env()

    def test_target_place_ids未設定の場合は設定エラーになる(self) -> None:
        _set_env(
            DB_CONNECTION_JSON=json.dumps(_VALID_DB_CONNECTION),
            PLACES_API_KEY="direct-api-key",
            GCP_PROJECT_ID="test-project",
        )
        with pytest.raises(ConfigurationError):
            load_config_from_env()

    def test_places_api_key未設定の場合は設定エラーになる(self) -> None:
        _set_env(
            DB_CONNECTION_JSON=json.dumps(_VALID_DB_CONNECTION),
            GCP_PROJECT_ID="test-project",
            TARGET_PLACE_IDS="place_1",
        )
        with pytest.raises(ConfigurationError):
            load_config_from_env()


class TestBuildDsn:
    """`build_dsn()`のテスト。"""

    def test_db接続情報からdsn文字列を組み立てる(self) -> None:
        dsn = build_dsn(_VALID_DB_CONNECTION)
        assert dsn == (
            "postgresql://app_user:secret-password@10.0.0.1:5432/app_db"
        )


class TestRunSyncJob:
    """`run_sync_job()`のテスト（DB/Places API呼び出しはモック化する）。"""

    def test_sync_vacant_propertiesの結果をそのまま返す(self) -> None:
        location = GeoPoint(latitude=35.0, longitude=135.0)
        details = PlaceDetailsResult(
            place_id="place_1",
            name="旧店舗",
            location=location,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=["restaurant"],
            address="テスト住所",
            phone_number=None,
            latest_review_time=datetime(2024, 1, 1),
        )

        mock_places_api_client = MagicMock()
        mock_places_api_client.get_place_details.return_value = details

        mock_repository = MagicMock()

        result = run_sync_job(
            mock_places_api_client, mock_repository, ["place_1"]
        )

        assert result == SyncResult(
            processed_count=1, detected_closure_count=1, error_count=0
        )
        mock_repository.upsert_by_place_id.assert_called_once()

    def test_places_api呼び出し失敗時はエラーカウントに加算し継続する(
        self,
    ) -> None:
        mock_places_api_client = MagicMock()
        mock_places_api_client.get_place_details.side_effect = PlacesApiError(
            "呼び出し失敗"
        )

        mock_repository = MagicMock()

        result = run_sync_job(
            mock_places_api_client, mock_repository, ["place_1", "place_2"]
        )

        assert result == SyncResult(
            processed_count=0, detected_closure_count=0, error_count=2
        )
        mock_repository.upsert_by_place_id.assert_not_called()

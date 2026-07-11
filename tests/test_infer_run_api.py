"""推論サービス（InferRun）のFastAPIエンドポイントの単体テスト。

`fastapi.testclient.TestClient`（httpxベース）を用いて、
`POST /generate`の正常系（モック認証成功時）・異常系（認証失敗時）と、
`prompt`/`context_snippets`が空の場合のトークン数の整合性を検証する。

Validates: Requirements 7.1, 7.2, 7.3, 12.1
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from regional_revitalization.infer_run_api import (
    DEFAULT_MOCK_TOKEN,
    app,
    set_inference_client,
)
from regional_revitalization.inference import MockInferenceClient


@pytest.fixture(autouse=True)
def _reset_environment_and_client() -> None:
    """各テスト前に環境変数・共有インスタンスをデフォルト状態へリセットする。

    テスト間の状態汚染を防ぐため`autouse=True`とする。
    """
    os.environ["REQUIRE_AUTH"] = "true"
    os.environ.pop("INFER_RUN_EXPECTED_TOKEN", None)
    set_inference_client(MockInferenceClient())
    yield
    os.environ.pop("REQUIRE_AUTH", None)
    os.environ.pop("INFER_RUN_EXPECTED_TOKEN", None)


@pytest.fixture()
def client() -> TestClient:
    """テスト用の`TestClient`を返す。"""
    return TestClient(app)


def _valid_payload() -> dict:
    return {
        "prompt": "子育て世帯向けの支援制度を知りたい",
        "context_snippets": ["道の駅 湖畔の郷: 地元産の農産物直売所"],
    }


def _auth_headers(token: str = DEFAULT_MOCK_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestGenerateAuth:
    """`POST /generate`のサービス間認証（モック認証）のテスト。

    Validates: Requirements 7.3, 12.1
    """

    def test_正しい認証ヘッダーの場合200を返す(self, client: TestClient) -> None:
        """モックトークンを含む正しい認証ヘッダーを付けた場合、

        200で`generated_text`/`input_tokens`/`output_tokens`を
        返すことを確認する（Requirements 7.1, 7.2）。
        """
        response = client.post(
            "/generate", json=_valid_payload(), headers=_auth_headers()
        )

        assert response.status_code == 200
        body = response.json()
        assert "generated_text" in body
        assert body["generated_text"] != ""
        assert isinstance(body["input_tokens"], int)
        assert isinstance(body["output_tokens"], int)
        assert body["input_tokens"] >= 0
        assert body["output_tokens"] >= 0

    def test_認証ヘッダーが無い場合403を返す(self, client: TestClient) -> None:
        """`Authorization`ヘッダーが無い場合に403が返ることを確認する

        （Requirements 7.3）。
        """
        response = client.post("/generate", json=_valid_payload())

        assert response.status_code == 403

    def test_トークンが不正な場合403を返す(self, client: TestClient) -> None:
        """`Authorization`ヘッダーのトークンが期待値と異なる場合に

        403が返ることを確認する（Requirements 7.3）。
        """
        response = client.post(
            "/generate",
            json=_valid_payload(),
            headers=_auth_headers("invalid-token"),
        )

        assert response.status_code == 403

    def test_Bearer形式でない場合403を返す(self, client: TestClient) -> None:
        """`Authorization`ヘッダーが`Bearer <token>`形式でない場合に

        403が返ることを確認する（Requirements 7.3）。
        """
        response = client.post(
            "/generate",
            json=_valid_payload(),
            headers={"Authorization": DEFAULT_MOCK_TOKEN},
        )

        assert response.status_code == 403

    def test_カスタム期待トークンとの一致確認(self, client: TestClient) -> None:
        """環境変数`INFER_RUN_EXPECTED_TOKEN`でモックトークンを

        変更できることを確認する（Requirements 12.1）。
        """
        os.environ["INFER_RUN_EXPECTED_TOKEN"] = "custom-token"

        response = client.post(
            "/generate",
            json=_valid_payload(),
            headers=_auth_headers("custom-token"),
        )

        assert response.status_code == 200

    def test_REQUIRE_AUTHがfalseの場合認証ヘッダー無しでも200を返す(
        self, client: TestClient
    ) -> None:
        """`REQUIRE_AUTH=false`の場合、認証ヘッダー無しでもモック認証を

        スキップして200を返すことを確認する（ローカルテスト向け）。
        """
        os.environ["REQUIRE_AUTH"] = "false"

        response = client.post("/generate", json=_valid_payload())

        assert response.status_code == 200


class TestGenerateTokenCounts:
    """`POST /generate`の入出力トークン数の整合性テスト。

    Validates: Requirements 7.2
    """

    def test_context_snippetsが空リストでもトークン数は0以上(
        self, client: TestClient
    ) -> None:
        """`context_snippets`が空リストの場合でも`input_tokens`/

        `output_tokens`が0以上の整数であることを確認する
        （Requirements 7.2）。
        """
        payload = {
            "prompt": "空き家活用の事例",
            "context_snippets": [],
        }

        response = client.post(
            "/generate", json=payload, headers=_auth_headers()
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["input_tokens"], int)
        assert isinstance(body["output_tokens"], int)
        assert body["input_tokens"] >= 0
        assert body["output_tokens"] >= 0

    def test_promptが空文字列でもトークン数は0以上(
        self, client: TestClient
    ) -> None:
        """`prompt`が空文字列の場合でも`input_tokens`/`output_tokens`が

        0以上の整数であることを確認する（Requirements 7.2）。
        """
        payload = {
            "prompt": "",
            "context_snippets": ["何らかのコンテキスト"],
        }

        response = client.post(
            "/generate", json=payload, headers=_auth_headers()
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["input_tokens"], int)
        assert isinstance(body["output_tokens"], int)
        assert body["input_tokens"] >= 0
        assert body["output_tokens"] >= 0

    def test_promptもcontext_snippetsも空の場合トークン数は0以上(
        self, client: TestClient
    ) -> None:
        """`prompt`が空文字列かつ`context_snippets`が空リストの場合でも

        `input_tokens`/`output_tokens`が0以上の整数であることを
        確認する（Requirements 7.2）。
        """
        payload = {"prompt": "", "context_snippets": []}

        response = client.post(
            "/generate", json=payload, headers=_auth_headers()
        )

        assert response.status_code == 200
        body = response.json()
        assert body["input_tokens"] >= 0
        assert body["output_tokens"] >= 0

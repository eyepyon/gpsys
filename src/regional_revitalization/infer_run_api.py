"""推論サービス（InferRun）のFastAPI APIエンドポイント実装。

`design.md`の「コンポーネント2: 推論サービス (InferRun)」に基づき、
`POST /generate`エンドポイントを実装する。

**責務境界**: InferRunはビジネスロジック（検索・re-rank）を持たず、
プロンプトと生成済みコンテキストを受け取ってテキストを生成するだけの
薄いサービスとする（`inference.MockInferenceClient.generate_with_tokens()`
相当のロジックを呼び出すのみ）。

**サービス間認証について（Requirements 7.1, 7.3, 12.1）**:
本番運用では、アプリ本体サービス（APIRun）から推論サービス（InferRun）への
呼び出しはCloud RunのIAM認証（サービスアカウント経由の識別トークン）で
保護し、InferRunは`allUsers`に公開しない。Cloud Run側のIAM認証によって
アプリ本体サービス以外からの外部アクセスはインフラレベルで拒否されるため、
アプリケーションコード側で本来は認証トークンの検証処理を持つ必要は無い
（Cloud Run自体がIngress/IAMでリクエストを拒否する）。

ただし、ローカル実行・単体テストではCloud Run IAMの保護が働かないため、
本モジュールでは簡易的な「モック認証」の検証用依存性注入関数
`verify_service_auth()`を用意する。環境変数`REQUIRE_AUTH`が`"false"`の
場合は認証チェックをスキップし、それ以外（未設定を含む）の場合は
`Authorization: Bearer <token>`ヘッダーを検証する。期待するトークン文字列は
環境変数`INFER_RUN_EXPECTED_TOKEN`（未設定時は`"mock-service-token"`）と
比較し、ヘッダーが無い・形式が不正・トークンが一致しない場合は
403 Forbiddenを返す。

本番環境では`verify_service_auth()`をCloud Run IAM発行の識別トークン
（OIDCトークン）検証処理に置き換える想定である（例: Googleの
`google.oauth2.id_token.verify_oauth2_token()`等でトークンの署名・
audience・issuerを検証する）。
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from regional_revitalization.inference import (
    GenerateRequest,
    GenerateResponse,
    MockInferenceClient,
)

app = FastAPI(title="地方創生支援システム 推論サービス (InferRun)")


# --------------------------------------------------------------------------
# 依存性注入用の共有インスタンス
# --------------------------------------------------------------------------
# 実運用では実際のGemma 4 12B QATモデルを呼び出す実装に差し替える。
# デフォルトはテスト・ローカル実行向けのモック実装とする。
_inference_client: MockInferenceClient = MockInferenceClient()


def get_inference_client() -> MockInferenceClient:
    """共有の推論クライアントインスタンスを返す（`Depends`用）。"""
    return _inference_client


def set_inference_client(client: MockInferenceClient) -> None:
    """共有の推論クライアントインスタンスを差し替える。

    実運用環境（実際のGemma 4 12B QATモデル呼び出し）や結合テストで、
    デフォルトのモック実装から実装を切り替えるために使用する。
    """
    global _inference_client
    _inference_client = client


# --------------------------------------------------------------------------
# サービス間認証（モック認証 / 本番はCloud Run IAM認証に置き換える）
# --------------------------------------------------------------------------

#: モック認証で用いる、期待する固定トークン文字列のデフォルト値。
DEFAULT_MOCK_TOKEN = "mock-service-token"  # noqa: S105 - テスト用の固定トークン


def verify_service_auth(authorization: str | None = Header(default=None)) -> None:
    """サービス間認証（Cloud Run IAM認証）を検証する依存性注入関数。

    **本番運用**: 実際にはCloud RunのIngress設定・IAM認証（`allUsers`に
    公開しない設定、サービスアカウント経由の識別トークン）によって
    アプリ本体サービス以外からのアクセスはインフラレベルで拒否される。
    本番デプロイ時は、本関数を識別トークン（OIDCトークン）の署名・
    audience検証を行う実装に置き換える想定である。

    **ローカルテスト**: 環境変数`REQUIRE_AUTH`が`"false"`（大文字小文字を
    区別しない）の場合は検証をスキップする。それ以外の場合は
    `Authorization: Bearer <token>`ヘッダーを検証し、`token`部分が
    環境変数`INFER_RUN_EXPECTED_TOKEN`（未設定時は`DEFAULT_MOCK_TOKEN`）と
    一致することを確認するモック認証を行う（Requirements 7.3, 12.1）。

    Args:
        authorization: `Authorization`HTTPヘッダーの値。未指定の場合はNone。

    Raises:
        HTTPException: 認証ヘッダーが無い、形式が不正、またはトークンが
            一致しない場合に403を発生させる。
    """
    require_auth = os.environ.get("REQUIRE_AUTH", "true").strip().lower() != "false"
    if not require_auth:
        return

    expected_token = os.environ.get("INFER_RUN_EXPECTED_TOKEN", DEFAULT_MOCK_TOKEN)

    if authorization is None:
        raise HTTPException(
            status_code=403, detail="Authorizationヘッダーが指定されていません"
        )

    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token or token != expected_token:
        raise HTTPException(
            status_code=403, detail="サービス間認証に失敗しました"
        )


# --------------------------------------------------------------------------
# リクエスト/レスポンスボディのPydanticモデル
# --------------------------------------------------------------------------


class GenerateRequestBody(BaseModel):
    """`POST /generate`のリクエストボディ。

    `design.md`の「コンポーネント2: 推論サービス (InferRun)」に定義された
    `GenerateRequest`に対応する。
    """

    prompt: str = Field(..., description="生成の元になるプロンプト文字列")
    context_snippets: list[str] = Field(
        default_factory=list,
        description="ハイブリッド検索結果を文字列化したコンテキスト一覧",
    )
    max_tokens: int = Field(default=512, description="生成する最大トークン数")
    temperature: float = Field(default=0.2, description="生成時のサンプリング温度")


class GenerateResponseBody(BaseModel):
    """`POST /generate`のレスポンスボディ。

    `design.md`の「コンポーネント2: 推論サービス (InferRun)」に定義された
    `GenerateResponse`に対応する。
    """

    generated_text: str
    input_tokens: int
    output_tokens: int


# --------------------------------------------------------------------------
# エンドポイント
# --------------------------------------------------------------------------


@app.post(
    "/generate",
    response_model=GenerateResponseBody,
    dependencies=[Depends(verify_service_auth)],
)
def generate(
    body: GenerateRequestBody,
) -> GenerateResponseBody:
    """生成リクエストを受け付け、Gemma 4 12B QATモデルによる生成結果を返す

    （Requirements 7.1, 7.2, 7.3, 12.1）。

    実際のGemma 4 12B QATモデルの呼び出しは行わず、
    `MockInferenceClient.generate_with_tokens()`相当の簡易実装を用いて
    生成テキストと入力/出力トークン数を算出する。`prompt`が空文字列、
    `context_snippets`が空リストであっても`input_tokens`/`output_tokens`は
    0以上の整数を返す（Requirements 7.2）。

    サービス間認証（`verify_service_auth`）は`dependencies`として
    ルート全体に適用され、認証に失敗した場合は403を返す。
    """
    inference_client = get_inference_client()
    request = GenerateRequest(
        prompt=body.prompt,
        context_snippets=body.context_snippets,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
    )
    response: GenerateResponse = inference_client.generate_with_tokens(request)

    return GenerateResponseBody(
        generated_text=response.generated_text,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )

"""推論サービス連携（InferenceClient）の実装。

`design.md`の「コンポーネント1」内`InferenceClient` Protocol定義に基づき、
Gemma 4 12B QAT推論サービスクライアントのインターフェースと、
テスト用モック実装`MockInferenceClient`を実装する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from regional_revitalization.models import RegionalResource

if TYPE_CHECKING:
    # 型チェック時のみ`httpx`を参照する。実行時に未インストールでも
    # importエラーにならないようにするため、型ヒント専用の参照に留める。
    import httpx


@dataclass(frozen=True)
class GenerateRequest:
    """推論リクエスト

    `design.md`の「コンポーネント2: 推論サービス (InferRun)」に定義された
    `GenerateRequest`に対応する。

    Attributes:
        prompt: 生成の元になるプロンプト文字列。
        context_snippets: ハイブリッド検索結果を文字列化したコンテキスト一覧。
        max_tokens: 生成する最大トークン数。未指定時のデフォルトは512。
        temperature: 生成時のサンプリング温度。未指定時のデフォルトは0.2。
    """

    prompt: str
    context_snippets: list[str]
    max_tokens: int = 512
    temperature: float = 0.2


@dataclass(frozen=True)
class GenerateResponse:
    """推論レスポンス

    `design.md`の「コンポーネント2: 推論サービス (InferRun)」に定義された
    `GenerateResponse`に対応する。

    Attributes:
        generated_text: 生成されたテキスト。
        input_tokens: 入力（プロンプト+コンテキスト）のトークン数。0以上の整数。
        output_tokens: 生成テキストのトークン数。0以上の整数。
    """

    generated_text: str
    input_tokens: int
    output_tokens: int


class InferenceClient(Protocol):
    """Gemma 4 12B QAT 推論サービスクライアント"""

    def generate(self, query_text: str, context: list[RegionalResource]) -> str:
        """query_textと参照コンテキストを基に回答テキストを生成する。"""
        ...


class MockInferenceClient:
    """テスト用のインメモリ`InferenceClient`実装。

    固定文字列を返すモードと、渡された`context`の件数に応じた応答を返す
    モードの両方をサポートする。
    """

    def __init__(self, fixed_response: str | None = None) -> None:
        """モックの応答モードを初期化する。

        Args:
            fixed_response: 常にこの文字列を返す場合に指定する。
                Noneの場合は`context`の件数に応じた応答文字列を生成する。
        """
        self._fixed_response = fixed_response

    def generate(self, query_text: str, context: list[RegionalResource]) -> str:
        """固定応答、またはcontextの件数に応じた応答文字列を返す。

        Args:
            query_text: 利用者からの質問文。
            context: 回答生成の根拠として渡される地域資源一覧。

        Returns:
            固定応答文字列（`fixed_response`が指定されている場合）、または
            `query_text`と`context`の件数を含む応答文字列。
        """
        if self._fixed_response is not None:
            return self._fixed_response
        return f"「{query_text}」について、{len(context)}件の関連情報が見つかりました。"

    def generate_with_tokens(self, request: GenerateRequest) -> GenerateResponse:
        """`GenerateRequest`を受け取り、入出力トークン数を含む`GenerateResponse`を返す。

        トークン数は簡易的に空白区切りの単語数から算出する（Requirements 7.2）。
        `prompt`が空文字列、`context_snippets`が空リストの場合でも、
        `input_tokens`/`output_tokens`は0以上の整数（0を含む）となる。

        Args:
            request: プロンプト・コンテキストスニペット等を含む推論リクエスト。

        Returns:
            固定応答、またはプロンプトとコンテキスト件数に応じた応答文字列と、
            0以上の整数である`input_tokens`/`output_tokens`を含む`GenerateResponse`。
        """
        if self._fixed_response is not None:
            generated_text = self._fixed_response
        else:
            generated_text = (
                f"「{request.prompt}」について、"
                f"{len(request.context_snippets)}件の関連情報が見つかりました。"
            )

        # プロンプトの単語数 + 各コンテキストスニペットの単語数を入力トークン数とする
        input_tokens = len(request.prompt.split())
        for snippet in request.context_snippets:
            input_tokens += len(snippet.split())

        # 生成テキストの単語数を出力トークン数とする
        output_tokens = len(generated_text.split())

        return GenerateResponse(
            generated_text=generated_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class HttpInferenceClient:
    """推論サービス（InferRun）をHTTP経由で呼び出す`InferenceClient`実装。

    APIRunからInferRunへの呼び出しは、本番運用ではCloud RunのIAM認証
    （サービスアカウント経由の識別トークン）で保護される（Requirements 7.3,
    12.1）。本クラスは、Cloud Run環境で自動的に取得できるIDトークンを
    `Authorization: Bearer <token>`ヘッダーへ設定してリクエストする。
    ローカル実行等でIDトークンを取得できない場合は、認証ヘッダーを付与せずに
    リクエストする（InferRun側の`REQUIRE_AUTH=false`設定と組み合わせて使う想定）。

    `httpx`が実行環境にインストールされていない場合でも本モジュールの読み込み
    自体は失敗させず、実際にインスタンス化された時点でエラーとする。
    """

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        """推論サービスのベースURLとタイムアウト秒数を設定して初期化する。

        Args:
            base_url: 推論サービス（InferRun）のベースURL
                （例: ``https://regional-revitalization-infer-xxxxx.a.run.app``）。
            timeout_seconds: HTTPリクエストのタイムアウト秒数
                （design.mdのエラーシナリオ2: 推論サービスタイムアウトに対応）。

        Raises:
            RuntimeError: `httpx`パッケージが利用できない場合。
        """
        try:
            import httpx as _httpx
        except ImportError as exc:  # pragma: no cover - テスト環境に未インストールの場合
            raise RuntimeError(
                "推論サービスのHTTP呼び出しにはhttpxパッケージが必要です"
            ) from exc

        self._httpx = _httpx
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _build_headers(self) -> dict[str, str]:
        """Cloud Run環境で取得可能なIDトークンを含むヘッダーを組み立てる。

        Cloud Run上で実行されている場合、メタデータサーバーからIDトークンを
        取得できる。取得に失敗した場合（ローカル実行等）は認証ヘッダーを
        付与しない。
        """
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            token = google.oauth2.id_token.fetch_id_token(
                google.auth.transport.requests.Request(), self._base_url
            )
            return {"Authorization": f"Bearer {token}"}
        except Exception:  # noqa: BLE001 - ローカル実行等でIDトークンが取得できない場合を許容する
            return {}

    def generate(self, query_text: str, context: list[RegionalResource]) -> str:
        """推論サービスへHTTP POSTリクエストを送信し、生成テキストを返す。

        Args:
            query_text: 利用者からの質問文。
            context: 回答生成の根拠として渡す地域資源一覧。

        Returns:
            推論サービスが生成したテキスト。

        Raises:
            httpx.HTTPError: リクエストが失敗、またはタイムアウトした場合。
                呼び出し元（`generate_consultation_response()`）でそのまま
                伝播させ、502エラー等へ変換する。
        """
        context_snippets = [
            f"{resource.name}（{resource.category}）: {resource.description}"
            for resource in context
        ]
        response = self._httpx.post(
            f"{self._base_url}/generate",
            json={"prompt": query_text, "context_snippets": context_snippets},
            headers=self._build_headers(),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["generated_text"]

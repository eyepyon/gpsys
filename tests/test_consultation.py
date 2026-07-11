"""相談応答機能（`generate_consultation_response`）の単体テスト・プロパティテスト。"""

from datetime import datetime
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from regional_revitalization.consultation import generate_consultation_response
from regional_revitalization.inference import (
    GenerateRequest,
    MockInferenceClient,
)
from regional_revitalization.models import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    ConsultationRequest,
    GeoPoint,
    RegionalResource,
)
from regional_revitalization.repository import InMemoryResourceRepository, hybrid_search

# ベクトル検索テスト用のembedding次元数（テスト用に簡略化した次元数）
EMBEDDING_DIMENSION = 8

# GeoPointのランダム生成用戦略
geo_point_strategy = st.builds(
    GeoPoint,
    latitude=st.floats(min_value=LATITUDE_MIN, max_value=LATITUDE_MAX, allow_nan=False),
    longitude=st.floats(
        min_value=LONGITUDE_MIN, max_value=LONGITUDE_MAX, allow_nan=False
    ),
)

# 固定次元(EMBEDDING_DIMENSION)のembeddingベクトルのランダム生成用戦略
embedding_strategy = st.lists(
    st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
    min_size=EMBEDDING_DIMENSION,
    max_size=EMBEDDING_DIMENSION,
)


def _build_resource(location: GeoPoint, embedding: list[float]) -> RegionalResource:
    """テスト用の、指定した位置情報とembeddingを持つ`RegionalResource`を生成する。"""
    now = datetime.now()
    return RegionalResource(
        resource_id=uuid4(),
        name="テスト資源",
        category="テストカテゴリ",
        description="テスト用の説明文",
        location=location,
        file_url=None,
        embedding=embedding,
        created_at=now,
        updated_at=now,
    )


# ランダムな位置・embeddingを持つ地域資源データセットのランダム生成用戦略
resources_strategy = st.lists(
    st.tuples(geo_point_strategy, embedding_strategy), min_size=0, max_size=30
)


class TestGenerateConsultationResponseValidation:
    """相談リクエストの入力検証の単体テスト。

    Validates: Requirements 1.2, 1.3, 1.6
    """

    def _build_valid_kwargs(self) -> dict:
        """検証対象の引数を上書きするための、有効な入力一式を構築する。"""
        return {
            "query_text": "空き家を活用した創業支援について知りたい",
            "location": GeoPoint(latitude=35.4, longitude=138.9),
            "radius_km": 5.0,
        }

    def test_query_textが空文字列の場合検証エラーとなる(self) -> None:
        """`query_text`が空文字列の場合に`ValueError`が発生することを確認する。

        Validates: Requirements 1.2
        """
        repository = InMemoryResourceRepository()
        inference_client = MockInferenceClient()
        kwargs = self._build_valid_kwargs()
        kwargs["query_text"] = ""
        request = ConsultationRequest(**kwargs)

        with pytest.raises(ValueError):
            generate_consultation_response(repository, inference_client, request)

    @pytest.mark.parametrize("radius_km", [0.0, -1.0, -0.1])
    def test_radius_kmが0以下の場合検証エラーとなる(self, radius_km: float) -> None:
        """`radius_km`が0以下の場合に`ValueError`が発生することを確認する。

        Validates: Requirements 1.3
        """
        repository = InMemoryResourceRepository()
        inference_client = MockInferenceClient()
        kwargs = self._build_valid_kwargs()
        kwargs["radius_km"] = radius_km
        request = ConsultationRequest(**kwargs)

        with pytest.raises(ValueError):
            generate_consultation_response(repository, inference_client, request)

    def test_top_k未指定時にデフォルト値5が使用される(self) -> None:
        """`ConsultationRequest`生成時に`top_k`を指定しない場合、

        デフォルト値5が使用されることを確認する。

        Validates: Requirements 1.6
        """
        kwargs = self._build_valid_kwargs()
        request = ConsultationRequest(**kwargs)

        assert request.top_k == 5


class TestGenerateConsultationResponseProperties:
    """相談応答の正常系（参照資源の一致・生成テキストの非空性）のプロパティテスト。

    Validates: Requirements 1.4
    """

    @given(
        query_text=st.text(min_size=1, max_size=20),
        location=geo_point_strategy,
        radius_km=st.floats(
            min_value=1e-6, max_value=20000.0, allow_nan=False, allow_infinity=False
        ),
        top_k=st.integers(min_value=1, max_value=50),
        resources=resources_strategy,
    )
    @settings(max_examples=200)
    def test_参照資源の一致_生成テキストの非空性(
        self,
        query_text: str,
        location: GeoPoint,
        radius_km: float,
        top_k: int,
        resources: list[tuple[GeoPoint, list[float]]],
    ) -> None:
        """`generate_consultation_response()`の戻り値を検証する。

        - `referenced_resources`が`hybrid_search()`を直接呼び出した結果と
          一致すること（同じrepositoryとパラメータであれば決定的に同じ
          結果になる）
        - `generated_text`が空文字列でないこと
          （`MockInferenceClient`は常に非空文字列を返す実装のため）
        """
        built_resources = [
            _build_resource(res_location, embedding)
            for res_location, embedding in resources
        ]
        repository = InMemoryResourceRepository(built_resources)
        inference_client = MockInferenceClient()
        request = ConsultationRequest(
            query_text=query_text,
            location=location,
            radius_km=radius_km,
            top_k=top_k,
        )

        response = generate_consultation_response(
            repository, inference_client, request
        )

        expected_resources = hybrid_search(
            repository, query_text, location, radius_km, top_k
        )

        # referenced_resourcesがhybrid_searchの結果と一致すること
        assert response.referenced_resources == expected_resources

        # generated_textが空文字列でないこと
        assert response.generated_text != ""


class TestGenerateConsultationResponseErrorPropagation:
    """推論サービス失敗時のエラー伝播の単体テスト。

    Validates: Requirements 1.5, 7.4
    """

    def _build_valid_request(self) -> ConsultationRequest:
        """検証対象の呼び出しに使う、有効な`ConsultationRequest`を構築する。"""
        return ConsultationRequest(
            query_text="空き家を活用した創業支援について知りたい",
            location=GeoPoint(latitude=35.4, longitude=138.9),
            radius_km=5.0,
        )

    def test_generateが例外を発生させた場合に例外が伝播する(self) -> None:
        """`InferenceClient.generate()`が例外を発生させた場合、

        `generate_consultation_response()`が部分的な結果を返さずに
        その例外をそのまま伝播することを確認する。

        Validates: Requirements 1.5, 7.4
        """

        class RaisingInferenceClient:
            """`generate()`呼び出し時に必ず例外を発生させるモック実装。"""

            def generate(
                self, query_text: str, context: list[RegionalResource]
            ) -> str:
                raise ConnectionError("推論サービスへの接続に失敗しました")

        repository = InMemoryResourceRepository()
        inference_client = RaisingInferenceClient()
        request = self._build_valid_request()

        with pytest.raises(ConnectionError):
            generate_consultation_response(repository, inference_client, request)

    def test_generateがタイムアウトした場合に例外が伝播する(self) -> None:
        """`InferenceClient.generate()`がタイムアウトした場合、

        `generate_consultation_response()`が部分的な結果を返さずに
        その例外をそのまま伝播することを確認する。

        Validates: Requirements 1.5, 7.4
        """

        class TimingOutInferenceClient:
            """`generate()`呼び出し時に必ずタイムアウト例外を発生させるモック実装。"""

            def generate(
                self, query_text: str, context: list[RegionalResource]
            ) -> str:
                raise TimeoutError("推論サービスへのリクエストがタイムアウトしました")

        repository = InMemoryResourceRepository()
        inference_client = TimingOutInferenceClient()
        request = self._build_valid_request()

        with pytest.raises(TimeoutError):
            generate_consultation_response(repository, inference_client, request)


class TestMockInferenceClientTokenCounts:
    """`MockInferenceClient.generate_with_tokens()`の入出力トークン数の単体テスト。

    Validates: Requirements 7.2
    """

    def test_通常のプロンプト_コンテキストでトークン数が0以上の整数である(self) -> None:
        """通常のプロンプト・コンテキストで`input_tokens`/`output_tokens`が

        0以上の整数であることを確認する。

        Validates: Requirements 7.2
        """
        request = GenerateRequest(
            prompt="空き家を活用した創業支援について知りたい",
            context_snippets=["支援制度A", "支援制度B"],
        )
        client = MockInferenceClient()

        response = client.generate_with_tokens(request)

        assert isinstance(response.input_tokens, int)
        assert response.input_tokens >= 0
        assert isinstance(response.output_tokens, int)
        assert response.output_tokens >= 0

    def test_空のcontext_snippetsと空文字列のpromptでもトークン数が0以上の整数である(
        self,
    ) -> None:
        """`context_snippets`が空リスト、`prompt`が空文字列の場合でも、

        `input_tokens`/`output_tokens`が0以上の整数（0を含む）であることを
        確認する。

        Validates: Requirements 7.2
        """
        request = GenerateRequest(prompt="", context_snippets=[])
        client = MockInferenceClient()

        response = client.generate_with_tokens(request)

        assert isinstance(response.input_tokens, int)
        assert response.input_tokens >= 0
        assert isinstance(response.output_tokens, int)
        assert response.output_tokens >= 0

    def test_固定応答モードでもトークン数が0以上の整数である(self) -> None:
        """`fixed_response`指定時（空文字列の固定応答を含む）でも、

        `input_tokens`/`output_tokens`が0以上の整数であることを確認する。

        Validates: Requirements 7.2
        """
        request = GenerateRequest(prompt="", context_snippets=[])
        client = MockInferenceClient(fixed_response="")

        response = client.generate_with_tokens(request)

        assert isinstance(response.input_tokens, int)
        assert response.input_tokens >= 0
        assert isinstance(response.output_tokens, int)
        assert response.output_tokens >= 0

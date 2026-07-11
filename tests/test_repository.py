"""地理空間検索機能（`search_nearby_resources`）のプロパティベーステスト・単体テスト。"""

from datetime import datetime
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from regional_revitalization.models import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    GeoPoint,
    RegionalResource,
)
from regional_revitalization.registration import register_resource
from regional_revitalization.repository import (
    InMemoryResourceRepository,
    cosine_similarity,
    haversine_distance_km,
    hybrid_search,
    search_nearby_resources,
    search_similar_resources,
)
from regional_revitalization.storage import InMemoryStorageClient

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


def _build_resource(location: GeoPoint) -> RegionalResource:
    """テスト用の`RegionalResource`を生成する。"""
    now = datetime.now()
    return RegionalResource(
        resource_id=uuid4(),
        name="テスト資源",
        category="テストカテゴリ",
        description="テスト用の説明文",
        location=location,
        file_url=None,
        embedding=[],
        created_at=now,
        updated_at=now,
    )


# ランダムな位置を持つ地域資源データセットのランダム生成用戦略
resources_strategy = st.lists(
    geo_point_strategy.map(_build_resource), min_size=0, max_size=30
)


def _build_resource_with_embedding(embedding: list[float]) -> RegionalResource:
    """テスト用の、指定したembeddingを持つ`RegionalResource`を生成する。"""
    now = datetime.now()
    location = GeoPoint(latitude=0.0, longitude=0.0)
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


# 固定次元(EMBEDDING_DIMENSION)のembeddingベクトルのランダム生成用戦略
embedding_strategy = st.lists(
    st.floats(
        min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False
    ),
    min_size=EMBEDDING_DIMENSION,
    max_size=EMBEDDING_DIMENSION,
)

# ランダムなembeddingを持つ地域資源データセットのランダム生成用戦略
resources_with_embedding_strategy = st.lists(
    embedding_strategy.map(_build_resource_with_embedding), min_size=0, max_size=30
)


def _build_resource_with_location_and_embedding(
    location: GeoPoint, embedding: list[float]
) -> RegionalResource:
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


class TestSearchNearbyResourcesProperties:
    """地理空間検索の距離制約・順序性・件数制約のプロパティテスト。

    Validates: Requirements 2.1, 2.2, 2.3
    Property: Property 1, Property 2, Property 3
    """

    @given(
        location=geo_point_strategy,
        radius_km=st.floats(
            min_value=1e-6, max_value=20000.0, allow_nan=False, allow_infinity=False
        ),
        limit=st.integers(min_value=1, max_value=50),
        resources=resources_strategy,
    )
    @settings(max_examples=200)
    def test_距離制約_順序性_件数制約(
        self,
        location: GeoPoint,
        radius_km: float,
        limit: int,
        resources: list[RegionalResource],
    ) -> None:
        """Property 1, 2, 3を検証する。

        - Property 1（距離制約）: 戻り値の全資源について
          `location`との距離が`radius_km`以下であること
        - Property 2（件数制約）: 戻り値の件数が`limit`以下であること
        - Property 3（順序性）: 戻り値のリストが距離の昇順であること
        """
        repository = InMemoryResourceRepository(resources)

        result = search_nearby_resources(repository, location, radius_km, limit)

        # Property 2（件数制約）
        assert len(result) <= limit

        distances = [
            haversine_distance_km(location, resource.location) for resource in result
        ]

        # Property 1（距離制約）
        for distance in distances:
            assert distance <= radius_km

        # Property 3（順序性）: 距離の昇順（単調非減少）であること
        assert distances == sorted(distances)


class TestSearchNearbyResourcesValidation:
    """地理空間検索の入力検証と副作用なしの単体テスト。

    Validates: Requirements 2.4, 2.5
    """

    def _build_repository(self) -> InMemoryResourceRepository:
        """テスト用の初期データを持つリポジトリを構築する。"""
        location = GeoPoint(latitude=35.0, longitude=135.0)
        return InMemoryResourceRepository([_build_resource(location)])

    @pytest.mark.parametrize("radius_km", [0.0, -1.0, -100.0])
    def test_radius_km_が0以下の場合検証エラーとなる(self, radius_km: float) -> None:
        """`radius_km<=0`の場合に`ValueError`が発生することを確認する。

        Validates: Requirements 2.5
        """
        repository = self._build_repository()
        location = GeoPoint(latitude=35.0, longitude=135.0)

        with pytest.raises(ValueError):
            search_nearby_resources(repository, location, radius_km, limit=1)

    @pytest.mark.parametrize(
        "latitude,longitude",
        [
            (90.1, 0.0),
            (-90.1, 0.0),
            (0.0, 180.1),
            (0.0, -180.1),
        ],
    )
    def test_location_が範囲外の場合GeoPoint生成時に検証エラーとなる(
        self, latitude: float, longitude: float
    ) -> None:
        """範囲外の緯度経度を`GeoPoint`に渡すと生成時点で`ValueError`が発生することを確認する。

        `search_nearby_resources()`は`GeoPoint`を受け取る前提のため、
        不正な`location`は`GeoPoint`のコンストラクタ（`__post_init__`）で
        検証エラーとなる（Requirements 2.5）。
        """
        with pytest.raises(ValueError):
            GeoPoint(latitude=latitude, longitude=longitude)

    def test_正常系実行前後でリポジトリの内部状態が変化しない(self) -> None:
        """正常な検索実行の前後でリポジトリの件数が変化しないことを確認する。

        Validates: Requirements 2.4
        """
        repository = self._build_repository()
        location = GeoPoint(latitude=35.0, longitude=135.0)
        count_before = len(repository)

        search_nearby_resources(repository, location, radius_km=10.0, limit=5)

        assert len(repository) == count_before

    @pytest.mark.parametrize("radius_km", [0.0, -1.0])
    def test_エラー系実行前後でリポジトリの内部状態が変化しない(
        self, radius_km: float
    ) -> None:
        """検証エラーとなる呼び出しの前後でリポジトリの件数が変化しないことを確認する。

        Validates: Requirements 2.4
        """
        repository = self._build_repository()
        location = GeoPoint(latitude=35.0, longitude=135.0)
        count_before = len(repository)

        with pytest.raises(ValueError):
            search_nearby_resources(repository, location, radius_km, limit=1)

        assert len(repository) == count_before


class TestSearchSimilarResourcesProperties:
    """ベクトル検索の類似度順序性・件数制約のプロパティテスト。

    Validates: Requirements 3.1, 3.2
    Property: Property 4, Property 5
    """

    @given(
        embedding=embedding_strategy,
        top_k=st.integers(min_value=1, max_value=50),
        resources=resources_with_embedding_strategy,
    )
    @settings(max_examples=200)
    def test_順序性_件数制約(
        self,
        embedding: list[float],
        top_k: int,
        resources: list[RegionalResource],
    ) -> None:
        """Property 4, 5を検証する。

        - Property 4（件数制約）: 戻り値の件数が`top_k`以下であること
        - Property 5（順序性）: 戻り値がコサイン類似度の降順であること
        """
        repository = InMemoryResourceRepository(resources)

        result = search_similar_resources(repository, embedding, top_k)

        # Property 4（件数制約）
        assert len(result) <= top_k

        similarities = [
            cosine_similarity(embedding, resource.embedding) for resource in result
        ]

        # Property 5（順序性）: コサイン類似度の降順（単調非増加）であること
        assert similarities == sorted(similarities, reverse=True)


class TestSearchSimilarResourcesValidation:
    """ベクトル検索の次元不一致エラーと副作用なしの単体テスト。

    Validates: Requirements 3.3, 3.5
    """

    def _build_repository(self) -> InMemoryResourceRepository:
        """テスト用の、次元数EMBEDDING_DIMENSIONのembeddingを持つ初期データを構築する。"""
        embedding = [0.1] * EMBEDDING_DIMENSION
        return InMemoryResourceRepository([_build_resource_with_embedding(embedding)])

    @pytest.mark.parametrize("dimension", [4, 10])
    def test_次元数が異なるクエリembeddingを与えると検証エラーとなる(
        self, dimension: int
    ) -> None:
        """格納済みembeddingと異なる次元数のクエリembeddingを与えた場合に

        `ValueError`が発生することを確認する。

        Validates: Requirements 3.5
        """
        repository = self._build_repository()
        query_embedding = [0.1] * dimension

        with pytest.raises(ValueError):
            search_similar_resources(repository, query_embedding, top_k=1)

    @pytest.mark.parametrize("top_k", [0, -1, -10])
    def test_top_k_が1未満の場合検証エラーとなる(self, top_k: int) -> None:
        """`top_k<1`の場合に`ValueError`が発生することを確認する。

        Validates: Requirements 3.3
        """
        repository = self._build_repository()
        query_embedding = [0.1] * EMBEDDING_DIMENSION

        with pytest.raises(ValueError):
            search_similar_resources(repository, query_embedding, top_k=top_k)

    def test_正常系実行前後でリポジトリの内部状態が変化しない(self) -> None:
        """正常なベクトル検索実行の前後でリポジトリの件数が変化しないことを確認する。

        Validates: Requirements 3.5
        """
        repository = self._build_repository()
        query_embedding = [0.1] * EMBEDDING_DIMENSION
        count_before = len(repository)

        search_similar_resources(repository, query_embedding, top_k=5)

        assert len(repository) == count_before

    @pytest.mark.parametrize("dimension", [4, 10])
    def test_次元不一致エラー実行前後でリポジトリの内部状態が変化しない(
        self, dimension: int
    ) -> None:
        """次元不一致で検証エラーとなる呼び出しの前後でリポジトリの件数が

        変化しないことを確認する。

        Validates: Requirements 3.5
        """
        repository = self._build_repository()
        query_embedding = [0.1] * dimension
        count_before = len(repository)

        with pytest.raises(ValueError):
            search_similar_resources(repository, query_embedding, top_k=1)

        assert len(repository) == count_before

    @pytest.mark.parametrize("top_k", [0, -1])
    def test_top_k検証エラー実行前後でリポジトリの内部状態が変化しない(
        self, top_k: int
    ) -> None:
        """`top_k<1`で検証エラーとなる呼び出しの前後でリポジトリの件数が

        変化しないことを確認する。

        Validates: Requirements 3.3
        """
        repository = self._build_repository()
        query_embedding = [0.1] * EMBEDDING_DIMENSION
        count_before = len(repository)

        with pytest.raises(ValueError):
            search_similar_resources(repository, query_embedding, top_k=top_k)

        assert len(repository) == count_before


class TestHybridSearchProperties:
    """ハイブリッド検索の一意性・件数制約・地理的整合性のプロパティテスト。

    Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.6, 4.7
    Property: Property 6, Property 7, Property 11
    """

    @given(
        query_text=st.text(min_size=1, max_size=20),
        location=geo_point_strategy,
        radius_km=st.floats(
            min_value=1e-6, max_value=20000.0, allow_nan=False, allow_infinity=False
        ),
        top_k=st.integers(min_value=1, max_value=50),
        resources=st.lists(
            st.tuples(geo_point_strategy, embedding_strategy), min_size=0, max_size=30
        ),
    )
    @settings(max_examples=200)
    def test_一意性_件数制約_地理的整合性(
        self,
        query_text: str,
        location: GeoPoint,
        radius_km: float,
        top_k: int,
        resources: list[tuple[GeoPoint, list[float]]],
    ) -> None:
        """Property 6, 7, 11を検証する。

        - Property 6（一意性）: 戻り値に同一`resource_id`が2回以上出現しないこと
        - Property 7（件数制約）: 戻り値の件数が`min(候補集合のサイズ, top_k)`と
          一致すること（候補集合が0件の場合は空リストとなること）
        - Property 11（地理的整合性）: 戻り値に含まれる全ての資源について、
          `location`との地理的距離が`radius_km`以下であること
        """
        built_resources = [
            _build_resource_with_location_and_embedding(res_location, embedding)
            for res_location, embedding in resources
        ]
        repository = InMemoryResourceRepository(built_resources)

        result = hybrid_search(repository, query_text, location, radius_km, top_k)

        # Property 6（一意性）
        result_ids = [resource.resource_id for resource in result]
        assert len(result_ids) == len(set(result_ids))

        # 候補集合（半径radius_km以内の資源）のサイズを別途計算する
        candidate_count = sum(
            1
            for resource in built_resources
            if haversine_distance_km(location, resource.location) <= radius_km
        )

        # Property 7（件数制約）
        assert len(result) == min(candidate_count, top_k)
        if candidate_count == 0:
            assert result == []

        # Property 11（地理的整合性）
        for resource in result:
            assert haversine_distance_km(location, resource.location) <= radius_km


# SQLメタ文字（シングルクォート、セミコロン、SQLコメント記号等）を含む文字列の
# ランダム生成用戦略。パラメータ化クエリであればこれらの文字が含まれていても
# 例外を発生させず、入力値がそのまま保存・比較に使われることを検証する。
sql_meta_characters = ["'", ";", "--", "/*", "*/", '"', "\\", "%", "OR 1=1"]


def _text_with_sql_meta_characters(min_size: int = 1, max_size: int = 30):
    """通常文字とSQLメタ文字を混在させたテキストのHypothesis戦略を返す。"""
    return st.lists(
        st.one_of(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs",), min_codepoint=0x20
                ),
                min_size=1,
                max_size=5,
            ),
            st.sampled_from(sql_meta_characters),
        ),
        min_size=min_size,
        max_size=max_size,
    ).map(lambda parts: "".join(parts))


class TestSqlInjectionResistanceProperties:
    """SQLメタ文字を含む入力に対するプロパティテスト。

    `register_resource()`や`hybrid_search()`はパラメータ化クエリ
    （プレースホルダ）で実装される前提のため、シングルクォート・セミコロン・
    SQLコメント記号等を含む入力を与えても例外を発生させず、入力値が
    そのまま保存・比較に使われることを検証する（テスト用インメモリ実装で実施）。

    Validates: Requirements 12.2
    """

    @given(
        name=_text_with_sql_meta_characters(min_size=1, max_size=30),
        description=_text_with_sql_meta_characters(min_size=1, max_size=30),
        location=geo_point_strategy,
    )
    @settings(max_examples=100)
    def test_register_resourceがSQLメタ文字を含むnameとdescriptionを例外なく保存する(
        self,
        name: str,
        description: str,
        location: GeoPoint,
    ) -> None:
        """SQLメタ文字を含む`name`/`description`を与えても`register_resource()`が

        例外を発生させず、登録後に`get_by_id()`で取得した資源の`name`/
        `description`が入力値のままであることを確認する。
        """
        repository = InMemoryResourceRepository()
        storage_client = InMemoryStorageClient()

        resource = register_resource(
            repository,
            storage_client,
            name=name,
            category="テストカテゴリ",
            description=description,
            location=location,
            file_bytes=None,
            content_type=None,
        )

        fetched = repository.get_by_id(resource.resource_id)
        assert fetched is not None
        assert fetched.name == name
        assert fetched.description == description

    @given(
        query_text=_text_with_sql_meta_characters(min_size=1, max_size=30),
        location=geo_point_strategy,
        radius_km=st.floats(
            min_value=1e-6, max_value=20000.0, allow_nan=False, allow_infinity=False
        ),
        top_k=st.integers(min_value=1, max_value=50),
        resources=st.lists(
            st.tuples(geo_point_strategy, embedding_strategy), min_size=0, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_hybrid_searchがSQLメタ文字を含むquery_textを例外なく処理する(
        self,
        query_text: str,
        location: GeoPoint,
        radius_km: float,
        top_k: int,
        resources: list[tuple[GeoPoint, list[float]]],
    ) -> None:
        """SQLメタ文字を含む`query_text`を与えても`hybrid_search()`が

        例外を発生させないことを確認する。
        """
        built_resources = [
            _build_resource_with_location_and_embedding(res_location, embedding)
            for res_location, embedding in resources
        ]
        repository = InMemoryResourceRepository(built_resources)

        # 例外が発生しないことのみを確認する（戻り値の内容はProperty 6, 7, 11で
        # 別途検証済み）
        hybrid_search(repository, query_text, location, radius_km, top_k)

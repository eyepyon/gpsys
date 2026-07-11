"""地域資源登録機能（`register_resource`）の単体テスト・プロパティベーステスト。"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from regional_revitalization.models import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    GeoPoint,
)
from regional_revitalization.registration import register_resource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.storage import InMemoryStorageClient

# GeoPointのランダム生成用戦略
geo_point_strategy = st.builds(
    GeoPoint,
    latitude=st.floats(min_value=LATITUDE_MIN, max_value=LATITUDE_MAX, allow_nan=False),
    longitude=st.floats(
        min_value=LONGITUDE_MIN, max_value=LONGITUDE_MAX, allow_nan=False
    ),
)


class TestRegisterResourceValidation:
    """地域資源登録の入力検証の単体テスト。

    Validates: Requirements 5.6, 5.7, 5.8
    """

    def _build_valid_kwargs(self) -> dict:
        """検証対象の引数を上書きするための、有効な入力一式を構築する。"""
        return {
            "name": "道の駅 湖畔の郷",
            "category": "観光施設",
            "description": "地元産の農産物直売所と休憩施設。",
            "location": GeoPoint(latitude=35.4, longitude=138.9),
            "file_bytes": None,
            "content_type": None,
        }

    @pytest.mark.parametrize("field", ["name", "category", "description"])
    def test_name_category_descriptionが空文字列の場合検証エラーとなる(
        self, field: str
    ) -> None:
        """`name`/`category`/`description`のいずれかが空文字列の場合に

        `ValueError`が発生することを確認する。

        Validates: Requirements 5.6
        """
        repository = InMemoryResourceRepository()
        storage_client = InMemoryStorageClient()
        kwargs = self._build_valid_kwargs()
        kwargs[field] = ""

        with pytest.raises(ValueError):
            register_resource(repository, storage_client, **kwargs)

    @pytest.mark.parametrize(
        "latitude,longitude",
        [
            (90.1, 0.0),
            (-90.1, 0.0),
            (0.0, 180.1),
            (0.0, -180.1),
        ],
    )
    def test_locationが範囲外の場合GeoPoint生成時に検証エラーとなる(
        self, latitude: float, longitude: float
    ) -> None:
        """範囲外の緯度経度を`GeoPoint`に渡すと生成時点で`ValueError`が発生する

        ことを確認する。`register_resource()`は`GeoPoint`を受け取る前提のため、
        不正な`location`は`GeoPoint`のコンストラクタ（`__post_init__`）で
        検証エラーとなる（Requirements 5.7）。
        """
        with pytest.raises(ValueError):
            GeoPoint(latitude=latitude, longitude=longitude)

    def test_file_bytes指定時にcontent_typeが未指定の場合検証エラーとなる(
        self,
    ) -> None:
        """`file_bytes`が指定されているが`content_type`が未指定（None）の場合に

        `ValueError`が発生することを確認する。

        Validates: Requirements 5.8
        """
        repository = InMemoryResourceRepository()
        storage_client = InMemoryStorageClient()
        kwargs = self._build_valid_kwargs()
        kwargs["file_bytes"] = b"dummy-bytes"
        kwargs["content_type"] = None

        with pytest.raises(ValueError):
            register_resource(repository, storage_client, **kwargs)


class TestRegisterResourceUploadFailure:
    """アップロード失敗時の部分登録防止の単体テスト。

    `StorageClient.upload()`が例外を発生させた場合、`register_resource()`は
    その例外をそのまま伝播させ、`ResourceRepository.insert()`を呼び出さない
    （部分的な登録が発生しない）ことを確認する。

    Validates: Requirements 5.4
    """

    class _FailingStorageClient:
        """`upload()`呼び出し時に必ず例外を発生させるモック`StorageClient`。"""

        def upload(
            self, file_bytes: bytes, object_name: str, content_type: str
        ) -> str:
            """常に`ConnectionError`を発生させる。"""
            raise ConnectionError("ストレージへのアップロードに失敗しました")

    def test_アップロード失敗時に例外が伝播しinsertが呼ばれない(self) -> None:
        """`upload()`が例外を発生させた場合、`register_resource()`から

        その例外がそのまま伝播し、`resource_repository.insert()`が呼び出されない
        （リポジトリの件数が0のまま）ことを確認する。
        """
        repository = InMemoryResourceRepository()
        storage_client = self._FailingStorageClient()

        with pytest.raises(ConnectionError):
            register_resource(
                repository,
                storage_client,
                name="道の駅 湖畔の郷",
                category="観光施設",
                description="地元産の農産物直売所と休憩施設。",
                location=GeoPoint(latitude=35.4, longitude=138.9),
                file_bytes=b"dummy-bytes",
                content_type="application/octet-stream",
            )

        assert len(repository) == 0


class TestRegisterResourceFileUrlConsistency:
    """添付ファイル有無とfile_urlの整合性のプロパティベーステスト。

    Property 9（ファイル有無とURLの整合性）:
    `file_bytes is None ⟺ resource.file_url is None`が成立する。

    Validates: Requirements 5.2, 5.3
    Property: Property 9
    """

    @given(
        name=st.text(min_size=1, max_size=30),
        category=st.text(min_size=1, max_size=30),
        description=st.text(min_size=1, max_size=30),
        location=geo_point_strategy,
        file_bytes=st.one_of(st.none(), st.binary(min_size=1, max_size=100)),
    )
    @settings(max_examples=100)
    def test_file_bytesの有無とfile_urlの有無が一致する(
        self,
        name: str,
        category: str,
        description: str,
        location: GeoPoint,
        file_bytes: bytes | None,
    ) -> None:
        """`file_bytes`がNoneかどうかと、登録された資源の`file_url`がNoneかどうかが

        常に一致することを検証する（Property 9）。
        """
        # file_bytesが非Noneの場合はcontent_typeも指定する必要があるため、
        # ここで対応するcontent_typeを決定する。
        content_type = "application/octet-stream" if file_bytes is not None else None

        repository = InMemoryResourceRepository()
        storage_client = InMemoryStorageClient()

        resource = register_resource(
            repository,
            storage_client,
            name=name,
            category=category,
            description=description,
            location=location,
            file_bytes=file_bytes,
            content_type=content_type,
        )

        assert (file_bytes is None) == (resource.file_url is None)


class TestRegisterResourceRoundTrip:
    """登録の往復性（round-trip）のプロパティベーステスト。

    Property 8（round-trip）:
    `register_resource()`で登録した資源を`resource_id`で再取得すると、
    `name`, `category`, `description`, `location`が登録時の値と一致する。

    Validates: Requirements 5.5
    Property: Property 8
    """

    @given(
        name=st.text(min_size=1, max_size=30),
        category=st.text(min_size=1, max_size=30),
        description=st.text(min_size=1, max_size=30),
        location=geo_point_strategy,
        file_bytes=st.one_of(st.none(), st.binary(min_size=1, max_size=100)),
    )
    @settings(max_examples=100)
    def test_登録後にresource_idで再取得した資源が登録時の値と一致する(
        self,
        name: str,
        category: str,
        description: str,
        location: GeoPoint,
        file_bytes: bytes | None,
    ) -> None:
        """`register_resource()`で登録した資源を`resource_id`で再取得すると、

        `name`, `category`, `description`, `location`が登録時の値と
        一致することを検証する（Property 8）。
        """
        # file_bytesが非Noneの場合はcontent_typeも指定する必要があるため、
        # ここで対応するcontent_typeを決定する。
        content_type = "application/octet-stream" if file_bytes is not None else None

        repository = InMemoryResourceRepository()
        storage_client = InMemoryStorageClient()

        registered = register_resource(
            repository,
            storage_client,
            name=name,
            category=category,
            description=description,
            location=location,
            file_bytes=file_bytes,
            content_type=content_type,
        )

        fetched = repository.get_by_id(registered.resource_id)

        assert fetched is not None
        assert fetched.name == name
        assert fetched.category == category
        assert fetched.description == description
        assert fetched.location == location

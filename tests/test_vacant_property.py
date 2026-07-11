"""居抜き物件データモデル（`VacantPropertyCandidate`）の検証ルールと

`InMemoryVacantPropertyRepository`の基本動作に関する単体テスト。
"""

from datetime import datetime, timedelta

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
from regional_revitalization.repository import haversine_distance_km
from regional_revitalization.vacant_property import (
    BusinessStatus,
    InMemoryVacantPropertyRepository,
    MockPlacesApiClient,
    PlaceDetailsResult,
    PlacesApiError,
    SyncResult,
    VacantPropertyCandidate,
    estimate_closure_period,
    search_vacant_properties,
    sync_vacant_properties,
)


def _build_candidate(
    place_id: str = "place-1",
    name: str = "旧店舗",
    location: GeoPoint | None = None,
    business_status: BusinessStatus = BusinessStatus.CLOSED_PERMANENTLY,
    types: list[str] | None = None,
    address: str | None = "東京都テスト区1-1-1",
    phone_number: str | None = "03-0000-0000",
    data_fetched_at: datetime | None = None,
    last_review_time: datetime | None = None,
    estimated_closure_period_start: datetime | None = None,
    estimated_closure_period_end: datetime | None = None,
) -> VacantPropertyCandidate:
    """テスト用の`VacantPropertyCandidate`を生成するヘルパー。"""
    now = datetime.now()
    return VacantPropertyCandidate(
        place_id=place_id,
        name=name,
        location=location if location is not None else GeoPoint(35.0, 135.0),
        business_status=business_status,
        types=types if types is not None else ["restaurant"],
        address=address,
        phone_number=phone_number,
        data_fetched_at=data_fetched_at if data_fetched_at is not None else now,
        last_review_time=last_review_time,
        estimated_closure_period_start=estimated_closure_period_start,
        estimated_closure_period_end=estimated_closure_period_end,
    )


class TestVacantPropertyCandidateValidation:
    """`VacantPropertyCandidate`の検証ルールに関する単体テスト。

    Validates: Requirements 13.2, 13.3, 14.4
    """

    def test_有効な値であれば例外を発生させない(self) -> None:
        """検証ルールをすべて満たす場合は正常に生成できることを確認する。"""
        now = datetime.now()
        candidate = _build_candidate(
            data_fetched_at=now,
            last_review_time=now - timedelta(days=1),
            estimated_closure_period_start=now - timedelta(days=1),
            estimated_closure_period_end=now,
        )
        assert candidate.place_id == "place-1"

    def test_place_idが空文字列の場合検証エラーとなる(self) -> None:
        """`place_id`が空文字列の場合に`ValueError`が発生することを確認する。"""
        with pytest.raises(ValueError):
            _build_candidate(place_id="")

    def test_nameが空文字列の場合検証エラーとなる(self) -> None:
        """`name`が空文字列の場合に`ValueError`が発生することを確認する。"""
        with pytest.raises(ValueError):
            _build_candidate(name="")

    def test_typesが空リストであれば例外を発生させない(self) -> None:
        """`types`が空リストの場合は許可されることを確認する。"""
        candidate = _build_candidate(types=[])
        assert candidate.types == []

    def test_last_review_timeがNoneかつ推定期間が非Noneの場合検証エラーとなる(
        self,
    ) -> None:
        """`last_review_time`がNoneなのに推定期間が設定されている場合に

        `ValueError`が発生することを確認する。
        """
        now = datetime.now()
        with pytest.raises(ValueError):
            _build_candidate(
                last_review_time=None,
                estimated_closure_period_start=now,
                estimated_closure_period_end=now,
            )

    def test_last_review_timeがNoneかつ推定期間も共にNoneであれば例外を発生させない(
        self,
    ) -> None:
        """`last_review_time`がNoneで推定期間も共にNoneの場合は許可されることを確認する。"""
        candidate = _build_candidate(
            last_review_time=None,
            estimated_closure_period_start=None,
            estimated_closure_period_end=None,
        )
        assert candidate.estimated_closure_period_start is None
        assert candidate.estimated_closure_period_end is None

    def test_推定期間のstartがendより後の場合検証エラーとなる(self) -> None:
        """`estimated_closure_period_start > estimated_closure_period_end`の場合に

        `ValueError`が発生することを確認する。
        """
        now = datetime.now()
        with pytest.raises(ValueError):
            _build_candidate(
                last_review_time=now - timedelta(days=2),
                estimated_closure_period_start=now,
                estimated_closure_period_end=now - timedelta(days=1),
            )

    def test_推定期間のstartとendが等しい場合は例外を発生させない(self) -> None:
        """`start == end`の場合は許可される（`start <= end`を満たすため）ことを確認する。"""
        now = datetime.now()
        candidate = _build_candidate(
            last_review_time=now - timedelta(days=1),
            estimated_closure_period_start=now,
            estimated_closure_period_end=now,
        )
        assert (
            candidate.estimated_closure_period_start
            == candidate.estimated_closure_period_end
        )

    def test_data_fetched_atが未来の時刻の場合検証エラーとなる(self) -> None:
        """`data_fetched_at`が未来の時刻の場合に`ValueError`が発生することを確認する。"""
        future = datetime.now() + timedelta(days=1)
        with pytest.raises(ValueError):
            _build_candidate(data_fetched_at=future)


class TestInMemoryVacantPropertyRepositoryUpsert:
    """`InMemoryVacantPropertyRepository.upsert_by_place_id()`の基本動作テスト。

    Validates: Requirements 13.2, 13.3
    """

    def test_新規のplace_idを追加できる(self) -> None:
        """未登録の`place_id`を`upsert_by_place_id()`すると新規追加されることを確認する。"""
        repository = InMemoryVacantPropertyRepository()
        candidate = _build_candidate(place_id="place-new")

        repository.upsert_by_place_id(candidate)

        assert len(repository) == 1

    def test_既存のplace_idを更新できる(self) -> None:
        """既存の`place_id`を`upsert_by_place_id()`すると上書き更新されることを確認する。"""
        repository = InMemoryVacantPropertyRepository()
        original = _build_candidate(place_id="place-1", name="旧店舗A")
        updated = _build_candidate(place_id="place-1", name="旧店舗B")

        repository.upsert_by_place_id(original)
        repository.upsert_by_place_id(updated)

        # 同一place_idについてレコードは常に1件のみである
        assert len(repository) == 1
        result = repository.search_by_business_status_and_type(
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            limit=10,
        )
        assert len(result) == 1
        assert result[0].name == "旧店舗B"

    def test_異なるplace_idはそれぞれ追加される(self) -> None:
        """異なる`place_id`を複数`upsert_by_place_id()`すると、それぞれ別レコードとして

        保持されることを確認する。
        """
        repository = InMemoryVacantPropertyRepository()
        repository.upsert_by_place_id(_build_candidate(place_id="place-1"))
        repository.upsert_by_place_id(_build_candidate(place_id="place-2"))

        assert len(repository) == 2


class TestSearchVacantProperties:
    """`search_vacant_properties()`の基本動作に関する単体テスト。

    Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
    """

    def test_radius_kmが0以下の場合ValueErrorとなる(self) -> None:
        """`radius_km`が0以下の場合に`ValueError`が発生することを確認する。"""
        repository = InMemoryVacantPropertyRepository()
        with pytest.raises(ValueError):
            search_vacant_properties(
                repository,
                location=GeoPoint(35.0, 135.0),
                radius_km=0.0,
                business_status=BusinessStatus.CLOSED_PERMANENTLY,
                types=None,
                limit=10,
            )

    def test_limitが1未満の場合ValueErrorとなる(self) -> None:
        """`limit`が1未満の場合に`ValueError`が発生することを確認する。"""
        repository = InMemoryVacantPropertyRepository()
        with pytest.raises(ValueError):
            search_vacant_properties(
                repository,
                location=GeoPoint(35.0, 135.0),
                radius_km=5.0,
                business_status=BusinessStatus.CLOSED_PERMANENTLY,
                types=None,
                limit=0,
            )

    def test_条件に合致する候補を返す(self) -> None:
        """`location`・`radius_km`・`business_status`・`types`の条件に合致する

        候補が返されることを確認する（Requirements 15.1, 15.2, 15.3, 15.4）。
        """
        repository = InMemoryVacantPropertyRepository(
            [
                _build_candidate(
                    place_id="place-near-match",
                    location=GeoPoint(35.0, 135.0),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["restaurant"],
                ),
                _build_candidate(
                    place_id="place-wrong-status",
                    location=GeoPoint(35.0, 135.0),
                    business_status=BusinessStatus.OPERATIONAL,
                    types=["restaurant"],
                ),
                _build_candidate(
                    place_id="place-wrong-type",
                    location=GeoPoint(35.0, 135.0),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["cafe"],
                ),
                _build_candidate(
                    place_id="place-far",
                    location=GeoPoint(36.0, 136.0),
                    business_status=BusinessStatus.CLOSED_PERMANENTLY,
                    types=["restaurant"],
                ),
            ]
        )

        result = search_vacant_properties(
            repository,
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=["restaurant"],
            limit=10,
        )

        assert [candidate.place_id for candidate in result] == ["place-near-match"]

    def test_limitで件数が制限される(self) -> None:
        """検索結果の件数が`limit`以下に制限されることを確認する（Requirements 15.5）。"""
        repository = InMemoryVacantPropertyRepository(
            [
                _build_candidate(place_id=f"place-{i}", location=GeoPoint(35.0, 135.0))
                for i in range(5)
            ]
        )

        result = search_vacant_properties(
            repository,
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            limit=2,
        )

        assert len(result) == 2

    def test_読み取り専用でリポジトリの内部状態を変更しない(self) -> None:
        """検索実行後もリポジトリの保持件数が変化しないことを確認する

        （Requirements 15.6）。
        """
        repository = InMemoryVacantPropertyRepository(
            [_build_candidate(place_id="place-1", location=GeoPoint(35.0, 135.0))]
        )

        search_vacant_properties(
            repository,
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            limit=10,
        )

        assert len(repository) == 1


class TestPlaceDetailsResultAndSyncResult:
    """`PlaceDetailsResult`, `SyncResult`データクラスの基本動作テスト。"""

    def test_PlaceDetailsResultを生成できる(self) -> None:
        """`PlaceDetailsResult`が正常に生成できることを確認する。"""
        result = PlaceDetailsResult(
            place_id="place-1",
            name="旧店舗",
            location=GeoPoint(35.0, 135.0),
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=["restaurant"],
            address="東京都テスト区1-1-1",
            phone_number="03-0000-0000",
            latest_review_time=datetime.now() - timedelta(days=1),
        )
        assert result.place_id == "place-1"
        assert result.business_status == BusinessStatus.CLOSED_PERMANENTLY

    def test_SyncResultを生成できる(self) -> None:
        """`SyncResult`が正常に生成できることを確認する。"""
        result = SyncResult(processed_count=3, detected_closure_count=1, error_count=0)
        assert result.processed_count == 3
        assert result.detected_closure_count == 1
        assert result.error_count == 0


class TestEstimateClosurePeriod:
    """`estimate_closure_period()`の基本動作に関する単体テスト。

    Validates: Requirements 14.1, 14.2, 14.3, 14.4
    """

    def test_last_review_timeがNoneの場合はNoneのタプルを返す(self) -> None:
        """`last_review_time`がNoneの場合、戻り値が`(None, None)`であることを確認する。"""
        data_fetched_at = datetime.now()

        result = estimate_closure_period(data_fetched_at, None)

        assert result == (None, None)

    def test_last_review_timeが非Noneの場合はlast_review_timeとdata_fetched_atのタプルを返す(
        self,
    ) -> None:
        """`last_review_time`が非Noneの場合、戻り値が

        `(last_review_time, data_fetched_at)`であることを確認する。
        """
        data_fetched_at = datetime.now()
        last_review_time = data_fetched_at - timedelta(days=3)

        start, end = estimate_closure_period(data_fetched_at, last_review_time)

        assert start == last_review_time
        assert end == data_fetched_at
        assert start <= end


# 同一place_idが複数回出現しやすくするため、少数の候補から選択する戦略
place_id_strategy = st.sampled_from(["place-a", "place-b", "place-c"])

# ランダムな`VacantPropertyCandidate`を生成するための戦略
candidate_strategy = st.builds(
    _build_candidate,
    place_id=place_id_strategy,
    name=st.sampled_from(["旧店舗A", "旧店舗B", "旧店舗C"]),
    business_status=st.sampled_from(list(BusinessStatus)),
)


class TestUpsertByPlaceIdUniquenessProperty:
    """`upsert_by_place_id()`のplace_id一意性に関するプロパティテスト。

    Property 12（place_idの一意性）: 任意の`place_id`に対し、同一`place_id`を
    持つレコードは1件以下しか存在しないことを検証する。

    Validates: Requirements 13.2
    """

    @settings(max_examples=100)
    @given(candidates=st.lists(candidate_strategy, min_size=0, max_size=30))
    def test_同一place_idの複数回UPSERT後もレコードは1件のみ(
        self, candidates: list[VacantPropertyCandidate]
    ) -> None:
        """同一`place_id`を含む複数回のUPSERTを行っても、`place_id`ごとの

        レコードが常に1件以下であることを確認する（Property 12）。
        """
        repository = InMemoryVacantPropertyRepository()

        for candidate in candidates:
            repository.upsert_by_place_id(candidate)

        unique_place_ids = {candidate.place_id for candidate in candidates}

        # ユニークなplace_idの集合サイズと、実際に格納されているレコード数が一致する
        # （= 同一place_idを持つレコードは1件以下しか存在しない）
        assert len(repository) == len(unique_place_ids)


# `data_fetched_at`用の戦略。未来にならないよう過去〜現在の範囲でランダムな時刻を生成する
_data_fetched_at_strategy = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime.now(),
)


@st.composite
def _data_fetched_at_and_last_review_time_strategy(
    draw: st.DrawFn,
) -> tuple[datetime, datetime | None]:
    """`data_fetched_at`と、それに整合する`last_review_time`（None or 以前の時刻）を

    組で生成するHypothesis用の複合戦略。
    """
    data_fetched_at = draw(_data_fetched_at_strategy)
    last_review_time = draw(
        st.one_of(
            st.none(),
            st.datetimes(min_value=datetime(2000, 1, 1), max_value=data_fetched_at),
        )
    )
    return data_fetched_at, last_review_time


class TestEstimateClosurePeriodRangeConsistencyProperty:
    """`estimate_closure_period()`の廃業時期推定レンジ整合性に関するプロパティテスト。

    Property 16（廃業時期推定レンジの整合性）: `last_review_time is None ⟺
    (start, end) == (None, None)`が成立し、`last_review_time`が非Noneかつ
    `last_review_time <= data_fetched_at`の場合`start <= end`が成立することを検証する。

    Validates: Requirements 14.1, 14.2, 14.4
    """

    @settings(max_examples=200)
    @given(params=_data_fetched_at_and_last_review_time_strategy())
    def test_廃業時期推定レンジの整合性(
        self, params: tuple[datetime, datetime | None]
    ) -> None:
        """`last_review_time`のNone/非None双方のケースについて、

        推定レンジの整合性（Property 16）を検証する。
        """
        data_fetched_at, last_review_time = params

        start, end = estimate_closure_period(data_fetched_at, last_review_time)

        # last_review_time is None ⟺ (start, end) == (None, None)
        if last_review_time is None:
            assert (start, end) == (None, None)
        else:
            assert (start, end) != (None, None)

            # last_review_time <= data_fetched_atの場合、start <= endが成立する
            if last_review_time <= data_fetched_at:
                assert start is not None
                assert end is not None
                assert start <= end


# GeoPointのランダム生成用戦略（範囲内の緯度経度のみ）
_geo_point_strategy = st.builds(
    GeoPoint,
    latitude=st.floats(min_value=LATITUDE_MIN, max_value=LATITUDE_MAX, allow_nan=False),
    longitude=st.floats(
        min_value=LONGITUDE_MIN, max_value=LONGITUDE_MAX, allow_nan=False
    ),
)

# 業種タグ候補。この中から`types`及び候補の`types`をランダムに選択する
_type_tag_strategy = st.sampled_from(["restaurant", "cafe", "retail", "office", "hotel"])


@st.composite
def _search_candidates_strategy(
    draw: st.DrawFn,
) -> list[VacantPropertyCandidate]:
    """`place_id`が一意になるようランダムな居抜き物件候補データセットを生成する

    Hypothesis用の複合戦略。位置・`business_status`・`types`はランダムに
    生成し、半径内・半径外の候補が混在するケースを含む。
    """
    size = draw(st.integers(min_value=0, max_value=30))
    candidates: list[VacantPropertyCandidate] = []
    for i in range(size):
        location = draw(_geo_point_strategy)
        business_status = draw(st.sampled_from(list(BusinessStatus)))
        types = draw(st.lists(_type_tag_strategy, min_size=0, max_size=3, unique=True))
        candidates.append(
            _build_candidate(
                place_id=f"search-place-{i}",
                location=location,
                business_status=business_status,
                types=types,
            )
        )
    return candidates


class TestSearchVacantPropertiesProperties:
    """`search_vacant_properties()`の地理的整合性・業種フィルタ・件数制約に

    関するプロパティテスト。

    Validates: Requirements 15.2, 15.3, 15.4, 15.5
    Property: Property 13, Property 14, Property 15
    """

    @given(
        location=_geo_point_strategy,
        radius_km=st.floats(
            min_value=1e-6, max_value=20000.0, allow_nan=False, allow_infinity=False
        ),
        business_status=st.sampled_from(list(BusinessStatus)),
        types=st.one_of(
            st.none(),
            st.lists(_type_tag_strategy, min_size=1, max_size=3, unique=True),
        ),
        limit=st.integers(min_value=1, max_value=50),
        candidates=_search_candidates_strategy(),
    )
    @settings(max_examples=200)
    def test_地理的整合性_業種フィルタ_件数制約(
        self,
        location: GeoPoint,
        radius_km: float,
        business_status: BusinessStatus,
        types: list[str] | None,
        limit: int,
        candidates: list[VacantPropertyCandidate],
    ) -> None:
        """Property 13, 14, 15を検証する。

        - Property 14（地理的整合性）: 戻り値の全候補について`location`との
          距離が`radius_km`以下であること
        - Property 13（業種フィルタの正確性）: 戻り値の全候補について
          `business_status`が一致し、`types`指定時は積集合が空でないこと
        - Property 15（件数制約）: 戻り値の件数が`limit`以下であること
        """
        repository = InMemoryVacantPropertyRepository(candidates)

        result = search_vacant_properties(
            repository,
            location=location,
            radius_km=radius_km,
            business_status=business_status,
            types=types,
            limit=limit,
        )

        # Property 15（件数制約）
        assert len(result) <= limit

        for candidate in result:
            # Property 14（地理的整合性）
            assert haversine_distance_km(location, candidate.location) <= radius_km

            # Property 13（業種フィルタの正確性）
            assert candidate.business_status == business_status
            if types is not None:
                assert set(candidate.types) & set(types)


def _build_place_details(
    place_id: str = "place-1",
    name: str = "旧店舗",
    location: GeoPoint | None = None,
    business_status: BusinessStatus = BusinessStatus.CLOSED_PERMANENTLY,
    types: list[str] | None = None,
    address: str | None = "東京都テスト区1-1-1",
    phone_number: str | None = "03-0000-0000",
    latest_review_time: datetime | None = None,
) -> PlaceDetailsResult:
    """テスト用の`PlaceDetailsResult`を生成するヘルパー。"""
    return PlaceDetailsResult(
        place_id=place_id,
        name=name,
        location=location if location is not None else GeoPoint(35.0, 135.0),
        business_status=business_status,
        types=types if types is not None else ["restaurant"],
        address=address,
        phone_number=phone_number,
        latest_review_time=latest_review_time,
    )


class TestMockPlacesApiClient:
    """`MockPlacesApiClient`の基本動作に関する単体テスト。"""

    def test_登録済みplace_idの詳細を返す(self) -> None:
        """登録済みの`place_id`について、対応する`PlaceDetailsResult`が

        そのまま返されることを確認する。
        """
        details = _build_place_details(place_id="place-1")
        client = MockPlacesApiClient(details_by_place_id={"place-1": details})

        result = client.get_place_details("place-1")

        assert result is details

    def test_error_place_idsに含まれるplace_idはPlacesApiErrorとなる(self) -> None:
        """`error_place_ids`に指定した`place_id`を呼び出すと`PlacesApiError`が

        発生することを確認する。
        """
        client = MockPlacesApiClient(error_place_ids={"place-error"})

        with pytest.raises(PlacesApiError):
            client.get_place_details("place-error")

    def test_未登録のplace_idはPlacesApiErrorとなる(self) -> None:
        """辞書に登録されていない`place_id`を呼び出すと`PlacesApiError`が

        発生することを確認する。
        """
        client = MockPlacesApiClient()

        with pytest.raises(PlacesApiError):
            client.get_place_details("place-unknown")


class TestSyncVacantProperties:
    """`sync_vacant_properties()`の基本動作に関する単体テスト。

    Validates: Requirements 13.1, 13.3, 13.4
    """

    def test_target_place_idsが空リストの場合正常終了する(self) -> None:
        """空リストを渡した場合、`processed_count=0`で正常終了することを確認する。"""
        client = MockPlacesApiClient()
        repository = InMemoryVacantPropertyRepository()

        result = sync_vacant_properties(client, repository, [])

        assert result == SyncResult(
            processed_count=0, detected_closure_count=0, error_count=0
        )
        assert len(repository) == 0

    def test_CLOSED_PERMANENTLYを検知するとUPSERTされる(self) -> None:
        """`CLOSED_PERMANENTLY`が検知された`place_id`について、リポジトリに

        レコードが登録されることを確認する。
        """
        now = datetime.now()
        details = _build_place_details(
            place_id="place-closed",
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            latest_review_time=now - timedelta(days=10),
        )
        client = MockPlacesApiClient(details_by_place_id={"place-closed": details})
        repository = InMemoryVacantPropertyRepository()

        result = sync_vacant_properties(client, repository, ["place-closed"])

        assert result.processed_count == 1
        assert result.detected_closure_count == 1
        assert result.error_count == 0
        assert len(repository) == 1
        found = repository.search_by_business_status_and_type(
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            limit=10,
        )
        assert [candidate.place_id for candidate in found] == ["place-closed"]

    def test_OPERATIONALの場合は検知されずUPSERTされない(self) -> None:
        """`OPERATIONAL`等、`CLOSED_PERMANENTLY`以外の場合は検知されず、

        リポジトリにレコードが登録されないことを確認する。
        """
        details = _build_place_details(
            place_id="place-open", business_status=BusinessStatus.OPERATIONAL
        )
        client = MockPlacesApiClient(details_by_place_id={"place-open": details})
        repository = InMemoryVacantPropertyRepository()

        result = sync_vacant_properties(client, repository, ["place-open"])

        assert result.processed_count == 1
        assert result.detected_closure_count == 0
        assert result.error_count == 0
        assert len(repository) == 0

    def test_複数place_idを正常に処理する(self) -> None:
        """複数の`place_id`を渡した場合、それぞれ正しく処理されることを確認する。"""
        details_closed = _build_place_details(
            place_id="place-closed", business_status=BusinessStatus.CLOSED_PERMANENTLY
        )
        details_open = _build_place_details(
            place_id="place-open", business_status=BusinessStatus.OPERATIONAL
        )
        client = MockPlacesApiClient(
            details_by_place_id={
                "place-closed": details_closed,
                "place-open": details_open,
            }
        )
        repository = InMemoryVacantPropertyRepository()

        result = sync_vacant_properties(
            client, repository, ["place-closed", "place-open"]
        )

        assert result.processed_count == 2
        assert result.detected_closure_count == 1
        assert result.error_count == 0
        assert len(repository) == 1

    def test_一部のplace_idがエラーとなっても他のplace_idの処理が継続される(
        self,
    ) -> None:
        """一部の`place_id`でPlaces API呼び出しがエラーとなっても、当該`place_id`は

        スキップされて`error_count`に加算され、他の正常な`place_id`の処理は
        中断されずに継続されることを確認する（部分失敗許容、
        Requirements 13.2, 13.4）。
        """
        details_closed = _build_place_details(
            place_id="place-closed", business_status=BusinessStatus.CLOSED_PERMANENTLY
        )
        details_open = _build_place_details(
            place_id="place-open", business_status=BusinessStatus.OPERATIONAL
        )
        client = MockPlacesApiClient(
            details_by_place_id={
                "place-closed": details_closed,
                "place-open": details_open,
            },
            error_place_ids={"place-error-1", "place-error-2"},
        )
        repository = InMemoryVacantPropertyRepository()

        result = sync_vacant_properties(
            client,
            repository,
            ["place-error-1", "place-closed", "place-open", "place-error-2"],
        )

        # エラーとなったplace_idはerror_countに加算され、処理は継続する
        assert result.processed_count == 2
        assert result.detected_closure_count == 1
        assert result.error_count == 2

        # 正常に処理されたCLOSED_PERMANENTLYのplace_idのみがUPSERTされている
        assert len(repository) == 1
        found = repository.search_by_business_status_and_type(
            location=GeoPoint(35.0, 135.0),
            radius_km=1.0,
            business_status=BusinessStatus.CLOSED_PERMANENTLY,
            types=None,
            limit=10,
        )
        assert [candidate.place_id for candidate in found] == ["place-closed"]


# 同一place_idが複数回出現しやすくするため、少数のplace_idから選択する戦略
_sync_place_id_strategy = st.sampled_from(["sync-place-a", "sync-place-b", "sync-place-c"])

# `sync_vacant_properties()`への呼び出しリストをランダムに生成するための戦略
# （各呼び出しで対象となるplace_idのリスト。同一place_idが複数回・複数の呼び出しで
# 出現するケースを含む）
_sync_call_batches_strategy = st.lists(
    st.lists(_sync_place_id_strategy, min_size=0, max_size=5),
    min_size=1,
    max_size=5,
)


class TestSyncVacantPropertiesIdempotencyProperty:
    """`sync_vacant_properties()`の冪等性に関するプロパティテスト。

    同一`place_id`を含む`target_place_ids`を複数回渡してCLOSED_PERMANENTLYを
    繰り返し検知させても、リポジトリ内の該当`place_id`のレコードは常に1件のみ
    であることを検証する（Property 12との関連）。

    Validates: Requirements 13.2, 13.4
    """

    @settings(max_examples=100)
    @given(call_batches=_sync_call_batches_strategy)
    def test_同一place_idを複数回検知してもレコードは1件のみ(
        self, call_batches: list[list[str]]
    ) -> None:
        """すべての対象`place_id`が`CLOSED_PERMANENTLY`として検知される

        `MockPlacesApiClient`を使い、`sync_vacant_properties()`を複数回呼び出す。
        呼び出し後もリポジトリ内の該当`place_id`のレコードが1件のみであること
        （冪等性、Property 12）を確認する。
        """
        all_place_ids = {
            place_id for batch in call_batches for place_id in batch
        }
        details_by_place_id = {
            place_id: _build_place_details(
                place_id=place_id,
                business_status=BusinessStatus.CLOSED_PERMANENTLY,
            )
            for place_id in all_place_ids
        }
        client = MockPlacesApiClient(details_by_place_id=details_by_place_id)
        repository = InMemoryVacantPropertyRepository()

        for batch in call_batches:
            sync_vacant_properties(client, repository, batch)

        # 同一place_idを何度検知しても、リポジトリ内のレコード数は
        # ユニークなplace_id数と一致する（= 1件以下）
        assert len(repository) == len(all_place_ids)

        for place_id in all_place_ids:
            found = repository.search_by_business_status_and_type(
                location=GeoPoint(35.0, 135.0),
                radius_km=1.0,
                business_status=BusinessStatus.CLOSED_PERMANENTLY,
                types=None,
                limit=100,
            )
            matched = [c for c in found if c.place_id == place_id]
            assert len(matched) == 1

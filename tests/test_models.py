"""データモデル（GeoPoint, RegionalResource, ConsultationRequest, ConsultationResponse）の単体テスト。"""

from datetime import datetime
from uuid import uuid4

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from regional_revitalization.models import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    ConsultationRequest,
    ConsultationResponse,
    GeoPoint,
    RegionalResource,
)


class TestGeoPoint:
    """GeoPointの範囲検証ロジックに関するテスト。"""

    def test_有効な範囲内の値は例外を発生させない(self) -> None:
        point = GeoPoint(latitude=35.4, longitude=138.9)
        assert point.latitude == 35.4
        assert point.longitude == 138.9

    @pytest.mark.parametrize(
        "latitude,longitude",
        [
            (-90.0, -180.0),
            (90.0, 180.0),
            (0.0, 0.0),
        ],
    )
    def test_境界値は例外を発生させない(self, latitude: float, longitude: float) -> None:
        point = GeoPoint(latitude=latitude, longitude=longitude)
        assert point.latitude == latitude
        assert point.longitude == longitude

    def test_緯度が範囲外の場合ValueErrorを発生させる(self) -> None:
        with pytest.raises(ValueError):
            GeoPoint(latitude=90.1, longitude=0.0)
        with pytest.raises(ValueError):
            GeoPoint(latitude=-90.1, longitude=0.0)

    def test_経度が範囲外の場合ValueErrorを発生させる(self) -> None:
        with pytest.raises(ValueError):
            GeoPoint(latitude=0.0, longitude=180.1)
        with pytest.raises(ValueError):
            GeoPoint(latitude=0.0, longitude=-180.1)


class TestGeoPointRangeProperty:
    """GeoPointの範囲検証ロジックに関するプロパティベーステスト。

    Property 10（位置情報の範囲不変条件）:
    システムが受理する任意の`GeoPoint`について、常に
    `-90 <= latitude <= 90`かつ`-180 <= longitude <= 180`が成立する
    （不正な範囲の場合は検証エラーとして拒否される）。

    Validates: Requirements 6.1, 6.2, 6.3
    Property: Property 10
    """

    @given(
        latitude=st.floats(
            min_value=LATITUDE_MIN, max_value=LATITUDE_MAX, allow_nan=False
        ),
        longitude=st.floats(
            min_value=LONGITUDE_MIN, max_value=LONGITUDE_MAX, allow_nan=False
        ),
    )
    def test_範囲内の緯度経度は例外を発生させない(
        self, latitude: float, longitude: float
    ) -> None:
        """範囲内（境界値含む）の緯度・経度からは例外を発生させずGeoPointが生成できる。"""
        point = GeoPoint(latitude=latitude, longitude=longitude)
        assert LATITUDE_MIN <= point.latitude <= LATITUDE_MAX
        assert LONGITUDE_MIN <= point.longitude <= LONGITUDE_MAX

    @given(
        latitude=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
        longitude=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    )
    def test_範囲外の緯度または経度はValueErrorを発生させる(
        self, latitude: float, longitude: float
    ) -> None:
        """緯度・経度のいずれかが有効範囲外の場合は必ずValueErrorが発生する。"""
        assume(
            not (LATITUDE_MIN <= latitude <= LATITUDE_MAX)
            or not (LONGITUDE_MIN <= longitude <= LONGITUDE_MAX)
        )
        with pytest.raises(ValueError):
            GeoPoint(latitude=latitude, longitude=longitude)


class TestRegionalResource:
    """RegionalResourceデータクラスの基本的な動作確認。"""

    def test_正常なフィールドで生成できる(self) -> None:
        now = datetime.now()
        resource = RegionalResource(
            resource_id=uuid4(),
            name="道の駅",
            category="観光施設",
            description="地元産の農産物直売所",
            location=GeoPoint(latitude=35.4, longitude=138.9),
            file_url=None,
            embedding=[0.1, 0.2, 0.3],
            created_at=now,
            updated_at=now,
        )
        assert resource.name == "道の駅"
        assert resource.file_url is None


class TestConsultationRequestResponse:
    """ConsultationRequest / ConsultationResponseデータクラスの基本的な動作確認。"""

    def test_top_kのデフォルト値は5である(self) -> None:
        request = ConsultationRequest(
            query_text="子育て世帯向けの支援制度を知りたい",
            location=GeoPoint(latitude=35.4, longitude=138.9),
            radius_km=10.0,
        )
        assert request.top_k == 5

    def test_referenced_resourcesの未指定時は空リストである(self) -> None:
        response = ConsultationResponse(generated_text="回答文")
        assert response.referenced_resources == []

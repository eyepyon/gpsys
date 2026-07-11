"""Google Places API (Text Search) を実際にHTTP呼び出しする`PlacesSearchClient`実装。

`vacant_property_sync_job.py`の`RealPlacesApiClient`（Place Details API、
既知の`place_id`の詳細取得専用）とは異なり、本モジュールはText Search API
（位置・半径・キーワードによる検索、未知のスポットの発見用）を呼び出す。

管理画面（APIRun）から呼び出される想定であり、居抜き物件同期サービス
（Cloud Run Jobs）とはAPIキーのSecret Managerシークレットを分離する
（`terraform/main.tf`の`admin_places_api_key`変数参照）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from regional_revitalization.models import GeoPoint
from regional_revitalization.places_search import PlacesSearchClient
from regional_revitalization.vacant_property import (
    BusinessStatus,
    PlaceDetailsResult,
    PlacesApiError,
)

# Text Search (New) APIのフィールドマスク。Place Details APIと同様のフィールドを
# 取得するが、エンドポイント・レスポンス形式（`places`配列を含む）が異なる。
_PLACES_TEXT_SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.location,places.businessStatus,"
    "places.types,places.formattedAddress,places.internationalPhoneNumber"
)

_TEXT_SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"


class ConfigurationError(Exception):
    """必要なパッケージが利用できない等、実行環境の設定不備を表す例外。"""


def _parse_place_result(data: dict[str, Any]) -> PlaceDetailsResult | None:
    """Text Search APIレスポンス内の`places`配列の1要素を`PlaceDetailsResult`へ

    変換する。必須フィールドが欠落している場合は`None`を返し、その要素を
    スキップする（1件の解析失敗で検索全体を失敗させない）。
    """
    try:
        place_id = data["id"]
        name = data["displayName"]["text"]
        location_data = data["location"]
        location = GeoPoint(
            latitude=location_data["latitude"], longitude=location_data["longitude"]
        )
        business_status = BusinessStatus(data.get("businessStatus", "OPERATIONAL"))
        types = list(data.get("types", []))
        address = data.get("formattedAddress")
        phone_number = data.get("internationalPhoneNumber")
    except (KeyError, ValueError):
        return None

    return PlaceDetailsResult(
        place_id=place_id,
        name=name,
        location=location,
        business_status=business_status,
        types=types,
        address=address,
        phone_number=phone_number,
        latest_review_time=None,
    )


class RealPlacesSearchClient:
    """Google Places API (Text Search, New) を実際にHTTP呼び出しする

    `PlacesSearchClient`実装。
    """

    def __init__(self, api_key: str, timeout_seconds: float = 10.0) -> None:
        """APIキーとタイムアウト秒数を設定して初期化する。

        Raises:
            ConfigurationError: `httpx`パッケージが利用できない場合。
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - テスト環境に未インストールの場合
            raise ConfigurationError(
                "Places API呼び出しにはhttpxパッケージが必要です"
            ) from exc

        self._httpx = httpx
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search_text(
        self, location: GeoPoint, radius_km: float, keyword: str | None
    ) -> list[PlaceDetailsResult]:
        """指定した位置・半径・キーワードでText Search APIを呼び出す。

        Raises:
            PlacesApiError: HTTPリクエストが失敗した場合。
        """
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _PLACES_TEXT_SEARCH_FIELD_MASK,
        }
        body = {
            "textQuery": keyword or "店舗",
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                    },
                    "radius": radius_km * 1000.0,
                }
            },
        }
        try:
            response = self._httpx.post(
                _TEXT_SEARCH_ENDPOINT,
                headers=headers,
                json=body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except self._httpx.HTTPError as exc:
            raise PlacesApiError(f"Places API検索呼び出しに失敗しました: {exc}") from exc

        data = response.json()
        places = data.get("places", [])
        results = [_parse_place_result(place) for place in places]
        return [r for r in results if r is not None]

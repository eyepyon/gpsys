"""地方創生支援システムのデータモデル定義。

`design.md`の「コンポーネント1: アプリ本体サービス (APIRun)」および
「Data Models」章に定義された`GeoPoint`, `RegionalResource`,
`ConsultationRequest`, `ConsultationResponse`のデータクラスを実装する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

# 緯度の有効範囲（下限・上限）
LATITUDE_MIN = -90.0
LATITUDE_MAX = 90.0

# 経度の有効範囲（下限・上限）
LONGITUDE_MIN = -180.0
LONGITUDE_MAX = 180.0


@dataclass(frozen=True)
class GeoPoint:
    """地理座標（緯度・経度、EPSG:4326想定）

    Attributes:
        latitude: 緯度。-90.0以上90.0以下であること。
        longitude: 経度。-180.0以上180.0以下であること。

    Raises:
        ValueError: 緯度または経度が有効範囲外の場合に発生する。
    """

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """緯度・経度の範囲を検証する。

        範囲外の場合は`ValueError`を発生させる（Requirements 6.1, 6.2, 6.3）。
        """
        if not (LATITUDE_MIN <= self.latitude <= LATITUDE_MAX):
            raise ValueError(
                f"latitudeは{LATITUDE_MIN}以上{LATITUDE_MAX}以下である必要があります: "
                f"{self.latitude}"
            )
        if not (LONGITUDE_MIN <= self.longitude <= LONGITUDE_MAX):
            raise ValueError(
                f"longitudeは{LONGITUDE_MIN}以上{LONGITUDE_MAX}以下である必要があります: "
                f"{self.longitude}"
            )


@dataclass(frozen=True)
class RegionalResource:
    """地域資源（施設・イベント・支援制度等）

    Attributes:
        resource_id: 地域資源の一意識別子。
        name: 地域資源の名称（空文字列は不可）。
        category: 地域資源のカテゴリ。
        description: 地域資源の説明文。embedding生成の元データとなる。
        location: 地域資源の位置情報（有効な`GeoPoint`であること）。
        file_url: 添付ファイルのURL。添付ファイルが無い場合はNone。
        embedding: 説明文から生成されたベクトル表現。
            DB側（google_ml_integration拡張）で生成される。次元数は例: 768次元。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    resource_id: UUID
    name: str
    category: str
    description: str
    location: GeoPoint
    file_url: str | None
    embedding: list[float]
    created_at: datetime
    updated_at: datetime
    # 市町村別統計・管理画面での絞り込みのための列。既存データとの後方互換性の
    # ため、デフォルトは空文字列（「未設定」を意味する）とする。
    municipality: str = ""


@dataclass(frozen=True)
class ConsultationRequest:
    """相談リクエスト

    Attributes:
        query_text: 利用者からの質問文（空文字列は不可）。
        location: 利用者の位置情報。
        radius_km: 検索半径（キロメートル）。正の数であること。
        top_k: 生成時に利用する上位件数。未指定時のデフォルトは5。
    """

    query_text: str
    location: GeoPoint
    radius_km: float
    top_k: int = 5


@dataclass(frozen=True)
class ConsultationResponse:
    """相談応答

    Attributes:
        generated_text: 推論サービスが生成した回答テキスト。
        referenced_resources: 回答の根拠として参照した地域資源一覧。
    """

    generated_text: str
    referenced_resources: list[RegionalResource] = field(default_factory=list)

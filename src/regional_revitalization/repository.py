"""地域資源リポジトリ関連のインターフェースと実装。

`design.md`の「コンポーネント1: アプリ本体サービス (APIRun)」に定義された
`ResourceRepository` Protocolと、テスト用のインメモリ実装
`InMemoryResourceRepository`、および地理空間検索関数
`search_nearby_resources()`, ベクトル検索関数`search_similar_resources()`,
ハイブリッド検索関数`hybrid_search()`を実装する。
"""

from __future__ import annotations

import hashlib
import math
import struct
from datetime import datetime
from typing import Protocol
from uuid import UUID

from regional_revitalization.models import GeoPoint, RegionalResource

# 地球の半径（キロメートル）。Haversine公式による距離計算に使用する。
EARTH_RADIUS_KM = 6371.0

# インメモリ実装で擬似embeddingを生成する際のデフォルト次元数。
# 実運用時のCloud SQL `google_ml_integration`拡張が生成する次元数（768次元）とは
# 独立して、テスト用に簡略化した次元数を用いてもよい。
DEFAULT_PSEUDO_EMBEDDING_DIMENSION = 8


def _pseudo_embedding_from_text(
    text: str, dimension: int = DEFAULT_PSEUDO_EMBEDDING_DIMENSION
) -> list[float]:
    """query_textから決定的な擬似embeddingを生成する。

    実運用時はCloud SQLの`google_ml_integration`拡張がSQL関数呼び出し
    （`google_ml.embedding(...)`相当）によりDB側でembeddingを生成するが、
    `InMemoryResourceRepository`ではこの拡張の挙動をテスト用に模擬する必要がある。
    同一の`text`に対しては常に同一のベクトルを返す（決定的）。

    Args:
        text: embedding生成対象の文字列（query_text）。
        dimension: 生成するベクトルの次元数。

    Returns:
        `dimension`次元の擬似embeddingベクトル（各要素は-1.0以上1.0以下）。
    """
    # 文字列のSHA-256ハッシュ値をバイト列として取得し、
    # 一定バイト数ごとに符号なし整数へ変換して固定次元のベクトルに変換する。
    digest = hashlib.sha256(text.encode("utf-8")).digest()

    values: list[float] = []
    index = 0
    while len(values) < dimension:
        # ハッシュ値が短い場合はインデックスを変えて再ハッシュし、必要な長さを確保する。
        chunk = hashlib.sha256(digest + index.to_bytes(4, "big")).digest()
        for offset in range(0, len(chunk) - 3, 4):
            if len(values) >= dimension:
                break
            (raw_uint,) = struct.unpack_from(">I", chunk, offset)
            # 0以上1以下の値に正規化した後、-1.0以上1.0以下の範囲にスケールする。
            normalized = raw_uint / 0xFFFFFFFF
            values.append(normalized * 2.0 - 1.0)
        index += 1

    return values[:dimension]


def haversine_distance_km(point_a: GeoPoint, point_b: GeoPoint) -> float:
    """2つの地理座標間の距離をHaversine公式で計算する（キロメートル単位）。

    Args:
        point_a: 1つ目の地理座標。
        point_b: 2つ目の地理座標。

    Returns:
        2点間の地理的距離（キロメートル）。
    """
    lat1 = math.radians(point_a.latitude)
    lon1 = math.radians(point_a.longitude)
    lat2 = math.radians(point_b.latitude)
    lon2 = math.radians(point_b.longitude)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """2つのベクトル間のコサイン類似度を計算する。

    Args:
        vec_a: 1つ目のベクトル。
        vec_b: 2つ目のベクトル。

    Returns:
        -1.0以上1.0以下のコサイン類似度。いずれかのベクトルのノルムが0の場合は0.0を返す。

    Raises:
        ValueError: `vec_a`と`vec_b`の次元数が一致しない場合。
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"embeddingの次元数が一致しません: {len(vec_a)} != {len(vec_b)}"
        )

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class ResourceRepository(Protocol):
    """地域資源リポジトリ（Cloud SQL for PostgreSQLをバックエンドとする）"""

    def search_nearby(
        self, location: GeoPoint, radius_km: float, limit: int
    ) -> list[RegionalResource]:
        """指定した位置から半径radius_km以内の地域資源を、距離が近い順に返す。"""
        ...

    def search_similar(
        self, embedding: list[float], top_k: int
    ) -> list[RegionalResource]:
        """クエリembeddingとのコサイン類似度が高い順にtop_k件の地域資源を返す。"""
        ...

    def search_hybrid(
        self, query_text: str, location: GeoPoint, radius_km: float, top_k: int
    ) -> list[RegionalResource]:
        """単一SQLクエリで、半径radius_km以内に絞り込んだ候補集合の中から
        query_textとのベクトル類似度が高い順にtop_k件を返す。
        embeddingはgoogle_ml_integration拡張によりDB側で生成される。"""
        ...

    def insert(self, resource: RegionalResource) -> UUID:
        """地域資源を登録し、発行された`resource_id`を返す。"""
        ...

    def get_by_id(self, resource_id: UUID) -> RegionalResource | None:
        """`resource_id`に一致する地域資源を返す。存在しない場合はNoneを返す。

        登録が正常に完了した場合、一意な`resource_id`で登録済み資源を
        再取得できることを保証するために提供する（Requirements 5.5）。
        """
        ...

    def search_in_bounds(
        self,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        limit: int,
    ) -> list[RegionalResource]:
        """指定した緯度経度の矩形範囲内にある地域資源を返す（管理画面のマップ表示用）。"""
        ...

    def update(
        self,
        resource_id: UUID,
        name: str | None,
        category: str | None,
        description: str | None,
        location: GeoPoint | None,
        municipality: str | None,
    ) -> None:
        """指定した地域資源の属性を更新する。`None`が渡された項目は変更しない。

        `description`を変更する場合、embeddingもDB側で再生成される想定。
        """
        ...

    def delete(self, resource_id: UUID) -> None:
        """指定した地域資源を削除する。"""
        ...


class InMemoryResourceRepository:
    """テスト用のインメモリ`ResourceRepository`実装。

    内部にリストとして`RegionalResource`を保持し、
    Haversine公式による距離計算で地理空間検索を行う。
    """

    def __init__(self, resources: list[RegionalResource] | None = None) -> None:
        """内部データを初期化する。

        Args:
            resources: 初期データとして保持する地域資源のリスト。
                指定しない場合は空リストから開始する。
        """
        self._resources: list[RegionalResource] = list(resources) if resources else []

    def search_nearby(
        self, location: GeoPoint, radius_km: float, limit: int
    ) -> list[RegionalResource]:
        """指定した位置から半径radius_km以内の地域資源を、距離が近い順に返す。

        データベースへの読み取り専用操作を模し、内部状態を変更しない。
        """
        candidates = [
            (resource, haversine_distance_km(location, resource.location))
            for resource in self._resources
        ]
        within_radius = [
            (resource, distance)
            for resource, distance in candidates
            if distance <= radius_km
        ]
        within_radius.sort(key=lambda pair: pair[1])
        return [resource for resource, _ in within_radius[:limit]]

    def search_similar(
        self, embedding: list[float], top_k: int
    ) -> list[RegionalResource]:
        """クエリembeddingとのコサイン類似度が高い順にtop_k件の地域資源を返す。

        データベースへの読み取り専用操作を模し、内部状態を変更しない。

        Raises:
            ValueError: 格納済みのいずれかの`embedding`の次元数が
                クエリ`embedding`の次元数と一致しない場合。
        """
        candidates = [
            (resource, cosine_similarity(embedding, resource.embedding))
            for resource in self._resources
        ]
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return [resource for resource, _ in candidates[:top_k]]

    def search_hybrid(
        self, query_text: str, location: GeoPoint, radius_km: float, top_k: int
    ) -> list[RegionalResource]:
        """PostGIS絞り込み+pgvectorソートの段階的統合を単一SQLクエリの代わりに
        インメモリで再現する。

        Step 1: `haversine_distance_km`により`location`から半径`radius_km`以内の
        候補集合に絞り込む。
        Step 2: 候補集合が1件以上ある場合、query_textの擬似embeddingと各資源の
        `embedding`のコサイン類似度で降順ソートし`top_k`件に切り詰める。
        候補集合が0件の場合はコサイン類似度計算を行わず空リストを返す。

        データベースへの読み取り専用操作を模し、内部状態を変更しない。
        """
        candidates = [
            resource
            for resource in self._resources
            if haversine_distance_km(location, resource.location) <= radius_km
        ]

        if not candidates:
            return []

        query_embedding = _pseudo_embedding_from_text(
            query_text, dimension=len(candidates[0].embedding)
        )
        scored = [
            (resource, cosine_similarity(query_embedding, resource.embedding))
            for resource in candidates
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [resource for resource, _ in scored[:top_k]]

    def insert(self, resource: RegionalResource) -> UUID:
        """地域資源を内部リストに追加し、`resource_id`を返す。"""
        self._resources.append(resource)
        return resource.resource_id

    def get_by_id(self, resource_id: UUID) -> RegionalResource | None:
        """`resource_id`に一致する地域資源を内部リストから検索して返す。

        見つからない場合はNoneを返す（Requirements 5.5）。
        """
        for resource in self._resources:
            if resource.resource_id == resource_id:
                return resource
        return None

    def search_in_bounds(
        self,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        limit: int,
    ) -> list[RegionalResource]:
        """緯度経度の矩形範囲内にある地域資源を、内部リストの順序で最大`limit`件返す。"""
        matched = [
            resource
            for resource in self._resources
            if min_latitude <= resource.location.latitude <= max_latitude
            and min_longitude <= resource.location.longitude <= max_longitude
        ]
        return matched[:limit]

    def update(
        self,
        resource_id: UUID,
        name: str | None,
        category: str | None,
        description: str | None,
        location: GeoPoint | None,
        municipality: str | None,
    ) -> None:
        """`resource_id`に一致する地域資源の属性を内部リスト上で更新する。

        Raises:
            ValueError: 対象の`resource_id`が見つからない場合。
        """
        for index, resource in enumerate(self._resources):
            if resource.resource_id == resource_id:
                self._resources[index] = RegionalResource(
                    resource_id=resource.resource_id,
                    name=name if name is not None else resource.name,
                    category=category if category is not None else resource.category,
                    description=(
                        description if description is not None else resource.description
                    ),
                    location=location if location is not None else resource.location,
                    file_url=resource.file_url,
                    embedding=resource.embedding,
                    created_at=resource.created_at,
                    updated_at=datetime.now(),
                    municipality=(
                        municipality if municipality is not None else resource.municipality
                    ),
                )
                return
        raise ValueError(f"地域資源が見つかりません: {resource_id}")

    def delete(self, resource_id: UUID) -> None:
        """`resource_id`に一致する地域資源を内部リストから削除する。"""
        self._resources = [
            resource
            for resource in self._resources
            if resource.resource_id != resource_id
        ]

    def __len__(self) -> int:
        """保持している地域資源の件数を返す（テストでの副作用確認に使用）。"""
        return len(self._resources)


def search_nearby_resources(
    resource_repository: ResourceRepository,
    location: GeoPoint,
    radius_km: float,
    limit: int,
) -> list[RegionalResource]:
    """指定した位置から半径radius_km以内の地域資源を、距離が近い順に返す。

    事前条件を満たさない場合は`ValueError`を発生させる
    （Requirements 2.1, 2.2, 2.3, 2.5）。

    Args:
        resource_repository: 検索対象のリポジトリ。
        location: 検索基準となる位置情報。`GeoPoint`の`__post_init__`で
            緯度経度の範囲は既に検証されている。
        radius_km: 検索半径（キロメートル）。正の数であること。
        limit: 取得件数の上限。1以上の整数であること。

    Returns:
        `location`との地理的距離が`radius_km`以下の地域資源を、
        距離の昇順に並べたリスト（`limit`件以下）。

    Raises:
        ValueError: `radius_km`が0以下、または`limit`が1未満の場合。
    """
    if radius_km <= 0:
        raise ValueError(f"radius_kmは正の数である必要があります: {radius_km}")
    if limit < 1:
        raise ValueError(f"limitは1以上である必要があります: {limit}")

    return resource_repository.search_nearby(location, radius_km, limit)


def search_similar_resources(
    resource_repository: ResourceRepository,
    embedding: list[float],
    top_k: int,
) -> list[RegionalResource]:
    """クエリembeddingとのコサイン類似度が高い順にtop_k件の地域資源を返す。

    事前条件を満たさない場合は`ValueError`を発生させる
    （Requirements 3.1, 3.2, 3.3, 3.5）。

    Args:
        resource_repository: 検索対象のリポジトリ。
        embedding: クエリのembeddingベクトル。格納済みの地域資源の
            `embedding`と次元数が一致していること。
        top_k: 取得件数の上限。1以上の整数であること。

    Returns:
        クエリ`embedding`とのコサイン類似度が高い順に並べた地域資源のリスト
        （`top_k`件以下）。

    Raises:
        ValueError: `top_k`が1未満の場合、または`embedding`の次元数が
            格納済みデータの次元数と一致しない場合。
    """
    if top_k < 1:
        raise ValueError(f"top_kは1以上である必要があります: {top_k}")

    return resource_repository.search_similar(embedding, top_k)


def hybrid_search(
    resource_repository: ResourceRepository,
    query_text: str,
    location: GeoPoint,
    radius_km: float,
    top_k: int,
) -> list[RegionalResource]:
    """PostGISで半径radius_km以内に絞り込んだ候補集合の中から、
    query_textとのベクトル類似度が高い順にtop_k件を返す（単一SQLクエリ想定）。

    `resource_repository.search_hybrid(...)`を呼び出すだけの薄いラッパーであり、
    embedding生成・RRF統合・重複除去・スコア統合等のアプリ側ロジックは持たない
    （embeddingはDB側の`google_ml_integration`拡張で生成される）
    （Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7）。

    Args:
        resource_repository: 検索対象のリポジトリ。
        query_text: クエリ文字列。
        location: 検索基準となる位置情報。
        radius_km: 検索半径（キロメートル）。
        top_k: 取得件数の上限。

    Returns:
        `resource_repository.search_hybrid(...)`の戻り値。
    """
    return resource_repository.search_hybrid(query_text, location, radius_km, top_k)

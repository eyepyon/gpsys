"""管理画面向けの統計情報取得モジュール。

ダッシュボード・統計情報ページで使用する集計データを取得する。
`AdminStatsRepository` Protocolで抽象化し、Postgres実装
（`PostgresAdminStatsRepository`）とテスト用インメモリ実装を提供する。

集計対象:
- ダッシュボード概要（各テーブルの総件数、未対応の更新依頼件数）
- 市町村別データ数（regional_resources / vacant_property_candidates）
- 業種別データ数（vacant_property_candidates.typesの配列展開集計）
- ベクトルDB(pgvector)の分布状況（embeddingを2次元に圧縮した散布図用の座標、
  カテゴリ別のクラスタ数）

**embeddingの次元圧縮について**: 768次元のembeddingをブラウザで可視化するには
2次元程度への圧縮が必要である。scikit-learn等の重い依存関係を追加せず、
決定的で軽量な乱数射影（Random Projection、Johnson-Lindenstrauss変換の単純版）を
標準ライブラリのみで実装する。これは厳密なPCA/t-SNEではないが、
大まかな分布傾向を把握する用途には十分であり、追加の依存関係が不要という利点がある。
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover
    _asyncpg = None

# 2次元散布図用の乱数射影行列を生成する際の次元数。
PROJECTION_OUTPUT_DIMENSION = 2


@dataclass(frozen=True)
class DashboardSummary:
    """ダッシュボードの概要統計。

    Attributes:
        regional_resource_count: 地域資源の総件数。
        vacant_property_count: 居抜き物件候補の総件数。
        consultation_log_count: 相談履歴の総件数。
        pending_update_request_count: 未対応（pending）のデータ更新依頼件数。
        admin_user_count: 管理ユーザーの総数。
    """

    regional_resource_count: int
    vacant_property_count: int
    consultation_log_count: int
    pending_update_request_count: int
    admin_user_count: int
    all_store_count: int = 0


@dataclass(frozen=True)
class MunicipalityCount:
    """市町村別データ数の1件分。

    Attributes:
        municipality: 市町村名。空文字列は「未設定」を意味する。
        count: 件数。
    """

    municipality: str
    count: int


@dataclass(frozen=True)
class TypeCount:
    """業種別データ数の1件分。

    Attributes:
        type_tag: 業種タグ（例: "restaurant"）。
        count: 件数。
    """

    type_tag: str
    count: int


@dataclass(frozen=True)
class VectorPoint:
    """ベクトル分布散布図用の1点分。

    Attributes:
        resource_id: 対象地域資源のID（文字列化したUUID）。
        category: カテゴリ（クラスタ色分けに使用）。
        x: 2次元圧縮後のX座標。
        y: 2次元圧縮後のY座標。
    """

    resource_id: str
    category: str
    x: float
    y: float


@dataclass(frozen=True)
class ClusterCount:
    """カテゴリ別のクラスタ数（=カテゴリごとの件数）の1件分。

    Attributes:
        category: カテゴリ名。
        count: そのカテゴリに属する地域資源の件数。
    """

    category: str
    count: int


class AdminStatsRepository(Protocol):
    """管理画面向け統計情報の取得リポジトリ（Cloud SQLをバックエンドとする）。"""

    async def get_dashboard_summary(self) -> DashboardSummary:
        """ダッシュボード概要統計を返す。"""
        ...

    async def get_municipality_counts_resources(self) -> list[MunicipalityCount]:
        """地域資源の市町村別データ数を件数降順で返す。"""
        ...

    async def get_municipality_counts_vacant_properties(
        self,
    ) -> list[MunicipalityCount]:
        """居抜き物件候補の市町村別データ数を件数降順で返す。"""
        ...

    async def get_type_counts(self) -> list[TypeCount]:
        """居抜き物件候補の業種別（typesタグ展開）データ数を件数降順で返す。"""
        ...

    async def get_vector_points(self, limit: int) -> list[VectorPoint]:
        """地域資源のembeddingを2次元に圧縮した散布図用の点を最大`limit`件返す。"""
        ...

    async def get_cluster_counts(self) -> list[ClusterCount]:
        """カテゴリ別のクラスタ数（=カテゴリごとの地域資源件数）を件数降順で返す。"""
        ...


def _project_embedding_to_2d(embedding: list[float]) -> tuple[float, float]:
    """768次元等のembeddingベクトルを、決定的な乱数射影で2次元に圧縮する。

    Johnson-Lindenstrauss変換の簡易版として、embeddingの次元数に応じた
    固定シードの乱数射影行列（の各要素を都度ハッシュから決定的に導出）との
    内積をX/Y座標とする。scikit-learn等の追加依存を避けるための軽量実装であり、
    厳密なPCA/t-SNEの代替ではなく、大まかな分布傾向の可視化を目的とする。

    Args:
        embedding: embeddingベクトル。

    Returns:
        (x, y)の2次元座標。
    """
    if not embedding:
        return (0.0, 0.0)

    x = 0.0
    y = 0.0
    for index, value in enumerate(embedding):
        # 各次元インデックスから決定的な擬似乱数の重み(-1.0〜1.0)を2組導出し、
        # embeddingの値との内積を取ることで射影する。
        digest_x = hashlib.sha256(f"projX:{index}".encode("utf-8")).digest()
        digest_y = hashlib.sha256(f"projY:{index}".encode("utf-8")).digest()
        (raw_x,) = struct.unpack_from(">I", digest_x, 0)
        (raw_y,) = struct.unpack_from(">I", digest_y, 0)
        weight_x = (raw_x / 0xFFFFFFFF) * 2.0 - 1.0
        weight_y = (raw_y / 0xFFFFFFFF) * 2.0 - 1.0
        x += value * weight_x
        y += value * weight_y

    # 次元数で正規化し、ベクトル次元数に依存しないスケールに揃える。
    dimension = len(embedding)
    return (x / dimension, y / dimension)


class PostgresAdminStatsRepository:
    """Cloud SQL for PostgreSQLをバックエンドとする統計情報リポジトリ。"""

    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def get_dashboard_summary(self) -> DashboardSummary:
        resource_count = await self._count_rows("regional_resources")
        vacant_count = await self._count_rows("vacant_property_candidates")
        consultation_count = await self._count_rows("consultation_logs")
        pending_count = await self._count_rows(
            "resource_update_requests", "status = 'pending'"
        )
        admin_count = await self._count_rows("admin_users")
        places_table = await self._pool.fetchval(
            "SELECT to_regclass('places_search_results')"
        )
        all_store_count = (
            int(await self._pool.fetchval(
                "SELECT COUNT(DISTINCT place_id) FROM places_search_results"
            ))
            if places_table is not None
            else 0
        )
        return DashboardSummary(
            regional_resource_count=int(resource_count),
            vacant_property_count=int(vacant_count),
            consultation_log_count=int(consultation_count),
            pending_update_request_count=int(pending_count),
            admin_user_count=int(admin_count),
            all_store_count=all_store_count,
        )

    async def _count_rows(self, table_name: str, where: str | None = None) -> int:
        """Count a known dashboard table, treating an absent table as empty."""
        allowed_tables = {
            "regional_resources",
            "vacant_property_candidates",
            "consultation_logs",
            "resource_update_requests",
            "admin_users",
        }
        if table_name not in allowed_tables:
            raise ValueError(f"Unsupported dashboard table: {table_name}")
        exists = await self._pool.fetchval("SELECT to_regclass($1)", table_name)
        if exists is None:
            return 0
        query = f"SELECT COUNT(*) FROM {table_name}"
        if where:
            query += f" WHERE {where}"
        return int(await self._pool.fetchval(query))

    async def get_municipality_counts_resources(self) -> list[MunicipalityCount]:
        rows = await self._pool.fetch(
            """
            SELECT municipality, COUNT(*) AS c
            FROM regional_resources
            GROUP BY municipality
            ORDER BY c DESC
            """
        )
        return [
            MunicipalityCount(municipality=row["municipality"], count=int(row["c"]))
            for row in rows
        ]

    async def get_municipality_counts_vacant_properties(
        self,
    ) -> list[MunicipalityCount]:
        rows = await self._pool.fetch(
            """
            SELECT municipality, COUNT(*) AS c
            FROM vacant_property_candidates
            GROUP BY municipality
            ORDER BY c DESC
            """
        )
        return [
            MunicipalityCount(municipality=row["municipality"], count=int(row["c"]))
            for row in rows
        ]

    async def get_type_counts(self) -> list[TypeCount]:
        rows = await self._pool.fetch(
            """
            SELECT unnest(types) AS type_tag, COUNT(*) AS c
            FROM vacant_property_candidates
            GROUP BY type_tag
            ORDER BY c DESC
            """
        )
        return [
            TypeCount(type_tag=row["type_tag"], count=int(row["c"])) for row in rows
        ]

    async def get_vector_points(self, limit: int) -> list[VectorPoint]:
        rows = await self._pool.fetch(
            "SELECT resource_id, category, embedding FROM regional_resources LIMIT $1",
            limit,
        )
        points: list[VectorPoint] = []
        for row in rows:
            embedding = list(row["embedding"]) if row["embedding"] is not None else []
            x, y = _project_embedding_to_2d(embedding)
            points.append(
                VectorPoint(
                    resource_id=str(row["resource_id"]),
                    category=row["category"],
                    x=x,
                    y=y,
                )
            )
        return points

    async def get_cluster_counts(self) -> list[ClusterCount]:
        rows = await self._pool.fetch(
            """
            SELECT category, COUNT(*) AS c
            FROM regional_resources
            GROUP BY category
            ORDER BY c DESC
            """
        )
        return [
            ClusterCount(category=row["category"], count=int(row["c"]))
            for row in rows
        ]


class InMemoryAdminStatsRepository:
    """テスト・ローカル開発用のインメモリ`AdminStatsRepository`実装。

    `InMemoryResourceRepository`・`InMemoryVacantPropertyRepository`の内部データを
    直接参照して集計する。
    """

    def __init__(
        self,
        resource_repository: Any,
        vacant_property_repository: Any,
        admin_user_repository: Any,
        pending_update_request_count: int = 0,
        consultation_log_count: int = 0,
    ) -> None:
        self._resource_repository = resource_repository
        self._vacant_property_repository = vacant_property_repository
        self._admin_user_repository = admin_user_repository
        self._pending_update_request_count = pending_update_request_count
        self._consultation_log_count = consultation_log_count

    async def get_dashboard_summary(self) -> DashboardSummary:
        admin_count = await self._admin_user_repository.count()
        return DashboardSummary(
            regional_resource_count=len(self._resource_repository),
            vacant_property_count=len(self._vacant_property_repository),
            consultation_log_count=self._consultation_log_count,
            pending_update_request_count=self._pending_update_request_count,
            admin_user_count=admin_count,
        )

    async def get_municipality_counts_resources(self) -> list[MunicipalityCount]:
        return []

    async def get_municipality_counts_vacant_properties(
        self,
    ) -> list[MunicipalityCount]:
        return []

    async def get_type_counts(self) -> list[TypeCount]:
        return []

    async def get_vector_points(self, limit: int) -> list[VectorPoint]:
        return []

    async def get_cluster_counts(self) -> list[ClusterCount]:
        return []

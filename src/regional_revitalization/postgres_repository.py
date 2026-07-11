"""Cloud SQL for PostgreSQL用`ResourceRepository`実装のスケルトン。

`design.md`の「コンポーネント3: データストア (Cloud SQL for PostgreSQL)」および
「関数3: hybrid_search()」に記載されたスキーマ・SQL例（`ST_DWithin`, `<=>`演算子,
`google_ml.embedding(...)`）に基づき、`asyncpg`を用いたPostgreSQL実装を提供する。

**SQLインジェクション対策の方針（Requirements 12.2）**:
すべてのクエリは文字列連結でSQLを組み立てず、`asyncpg`のプレースホルダ
（`$1`, `$2`, ...）によるパラメータ化クエリとして構築する。ユーザー入力
（`name`, `description`, `query_text`等）はSQL文字列に直接埋め込まれることなく、
常にパラメータとして渡される。

**注意**: 本モジュールは実際のDB接続を行わないコード構造のみのスケルトンである。
接続文字列やコネクションプール（`asyncpg.Pool`）はコンストラクタで受け取る想定とし、
実際の接続確立・トランザクション管理は呼び出し側（アプリ起動処理等）の責務とする。
`asyncpg`が実行環境にインストールされていない場合でも本モジュールの読み込み自体が
失敗しないよう、importは`try/except ImportError`で保護し型ヒントのみに留める。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from regional_revitalization.models import GeoPoint, RegionalResource

if TYPE_CHECKING:
    # 型チェック時のみ`asyncpg`を参照する。実行時に未インストールでも
    # importエラーにならないようにするため、型ヒント専用の参照に留める。
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover - テスト環境に`asyncpg`が無い場合を想定
    _asyncpg = None


class PostgresResourceRepository:
    """Cloud SQL for PostgreSQL（PostGIS/pgvector/google_ml_integration拡張）を
    バックエンドとする`ResourceRepository`実装。

    `regional_revitalization.repository.ResourceRepository`（Protocol）を満たす。
    すべてのクエリはプレースホルダ（`$1`, `$2`, ...）でパラメータ化しており、
    ユーザー入力を文字列連結でSQLに埋め込むことはない（Requirements 12.2）。
    """

    def __init__(self, pool: "asyncpg.Pool") -> None:
        """コネクションプールを受け取って初期化する。

        Args:
            pool: `asyncpg.create_pool(...)`等で生成済みのコネクションプール。
                本クラスは接続確立自体は行わず、呼び出し側が用意したプールを
                受け取るだけである。
        """
        self._pool = pool

    async def search_nearby(
        self, location: GeoPoint, radius_km: float, limit: int
    ) -> list[RegionalResource]:
        """`ST_DWithin`により`location`から半径`radius_km`以内の地域資源を、
        距離が近い順に返す（パラメータ化クエリ）。

        Args:
            location: 検索基準となる位置情報。
            radius_km: 検索半径（キロメートル）。
            limit: 取得件数の上限。

        Returns:
            距離の昇順に並べた地域資源のリスト（`limit`件以下）。
        """
        query = """
            SELECT
                resource_id, name, category, description,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                file_url, embedding, created_at, updated_at, municipality
            FROM regional_resources
            WHERE ST_DWithin(
                location,
                ST_MakePoint($1, $2)::geography,
                $3
            )
            ORDER BY location <-> ST_MakePoint($1, $2)::geography
            LIMIT $4
        """
        # プレースホルダ $1=longitude, $2=latitude, $3=radius_km(メートル換算), $4=limit
        rows = await self._pool.fetch(
            query,
            location.longitude,
            location.latitude,
            radius_km * 1000.0,
            limit,
        )
        return [_row_to_resource(row) for row in rows]

    async def search_similar(
        self, embedding: list[float], top_k: int
    ) -> list[RegionalResource]:
        """pgvectorのコサイン距離演算子（`<=>`）により、クエリembeddingとの
        類似度が高い順にtop_k件の地域資源を返す（パラメータ化クエリ）。

        Args:
            embedding: クエリのembeddingベクトル。
            top_k: 取得件数の上限。

        Returns:
            コサイン類似度が高い順に並べた地域資源のリスト（`top_k`件以下）。
        """
        query = """
            SELECT
                resource_id, name, category, description,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                file_url, embedding, created_at, updated_at, municipality
            FROM regional_resources
            ORDER BY embedding <=> $1
            LIMIT $2
        """
        # プレースホルダ $1=embedding, $2=top_k
        rows = await self._pool.fetch(query, embedding, top_k)
        return [_row_to_resource(row) for row in rows]

    async def search_hybrid(
        self, query_text: str, location: GeoPoint, radius_km: float, top_k: int
    ) -> list[RegionalResource]:
        """`design.md`の「関数3: hybrid_search()」に記載された単一SQLクエリで、
        `ST_DWithin`による地理的絞り込みと、`google_ml.embedding(...)`により
        DB側で生成したクエリembeddingとのpgvectorコサイン距離（`<=>`演算子）
        による`ORDER BY`を組み合わせて実行する（パラメータ化クエリ）。

        Args:
            query_text: クエリ文字列。
            location: 検索基準となる位置情報。
            radius_km: 検索半径（キロメートル）。
            top_k: 取得件数の上限。

        Returns:
            半径`radius_km`以内に絞り込んだ候補集合の中から、
            `query_text`との類似度が高い順に並べた地域資源のリスト（`top_k`件以下）。
        """
        query = """
            SELECT
                resource_id, name, category, description,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                file_url, embedding, created_at, updated_at, municipality
            FROM regional_resources
            WHERE ST_DWithin(
                location,
                ST_MakePoint($1, $2)::geography,
                $3
            )
            ORDER BY embedding <=> google_ml.embedding($4)
            LIMIT $5
        """
        # プレースホルダ $1=longitude, $2=latitude, $3=radius_km(メートル換算),
        # $4=query_text, $5=top_k。query_textはSQL文字列に連結せず、常に
        # パラメータとして渡すためSQLインジェクションの余地がない。
        rows = await self._pool.fetch(
            query,
            location.longitude,
            location.latitude,
            radius_km * 1000.0,
            query_text,
            top_k,
        )
        return [_row_to_resource(row) for row in rows]

    async def insert(self, resource: RegionalResource) -> UUID:
        """地域資源を登録する（パラメータ化クエリ）。

        `embedding`列は`google_ml.embedding(description)`相当のSQL関数呼び出しで
        DB側から生成・格納する。`resource.embedding`（アプリ側のプレースホルダ）は
        INSERT対象に含めない。

        Args:
            resource: 登録する地域資源。`resource.embedding`はプレースホルダの
                ため無視され、DB側で生成されたembeddingが格納される。

        Returns:
            登録された`resource_id`。
        """
        query = """
            INSERT INTO regional_resources (
                resource_id, name, category, description, location,
                file_url, embedding, created_at, updated_at, municipality
            ) VALUES (
                $1, $2, $3, $4, ST_MakePoint($5, $6)::geography,
                $7, google_ml.embedding($4), $8, $9, $10
            )
            RETURNING resource_id
        """
        # プレースホルダ $1=resource_id, $2=name, $3=category, $4=description,
        # $5=longitude, $6=latitude, $7=file_url, $8=created_at, $9=updated_at,
        # $10=municipality
        # name/category/description等のユーザー入力は文字列連結せず、常に
        # パラメータとして渡すためSQLインジェクションの余地がない。
        row = await self._pool.fetchrow(
            query,
            resource.resource_id,
            resource.name,
            resource.category,
            resource.description,
            resource.location.longitude,
            resource.location.latitude,
            resource.file_url,
            resource.created_at,
            resource.updated_at,
            resource.municipality,
        )
        return row["resource_id"]

    async def get_by_id(self, resource_id: UUID) -> RegionalResource | None:
        """`resource_id`に一致する地域資源を返す（パラメータ化クエリ）。

        Args:
            resource_id: 検索対象の一意識別子。

        Returns:
            一致する`RegionalResource`。存在しない場合は`None`。
        """
        query = """
            SELECT
                resource_id, name, category, description,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                file_url, embedding, created_at, updated_at, municipality
            FROM regional_resources
            WHERE resource_id = $1
        """
        # プレースホルダ $1=resource_id
        row = await self._pool.fetchrow(query, resource_id)
        if row is None:
            return None
        return _row_to_resource(row)

    async def search_in_bounds(
        self,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        limit: int,
    ) -> list[RegionalResource]:
        """指定した緯度経度の矩形範囲内にある地域資源を返す（管理画面のマップ表示用）。

        `ST_MakeEnvelope`により矩形ジオメトリを構築し、`&&`演算子（バウンディング
        ボックスの重なり判定、GiSTインデックスを利用可能）で絞り込む。

        Args:
            min_latitude: 矩形範囲の南端緯度。
            min_longitude: 矩形範囲の西端経度。
            max_latitude: 矩形範囲の北端緯度。
            max_longitude: 矩形範囲の東端経度。
            limit: 取得件数の上限。
        """
        query = """
            SELECT
                resource_id, name, category, description,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                file_url, embedding, created_at, updated_at, municipality
            FROM regional_resources
            WHERE location::geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
            LIMIT $5
        """
        # プレースホルダ $1=min_longitude, $2=min_latitude,
        # $3=max_longitude, $4=max_latitude, $5=limit
        rows = await self._pool.fetch(
            query, min_longitude, min_latitude, max_longitude, max_latitude, limit
        )
        return [_row_to_resource(row) for row in rows]

    async def update(
        self,
        resource_id: UUID,
        name: str | None,
        category: str | None,
        description: str | None,
        location: GeoPoint | None,
        municipality: str | None,
    ) -> None:
        """指定した地域資源の属性を更新する（パラメータ化クエリ）。

        `description`が指定された場合、embeddingは`google_ml.embedding(...)`で
        再生成する。`location`が指定された場合は`ST_MakePoint`で変換する。
        `None`が渡された項目はCOALESCEにより変更しない。
        """
        query = """
            UPDATE regional_resources
            SET
                name = COALESCE($2, name),
                category = COALESCE($3, category),
                description = COALESCE($4, description),
                embedding = CASE
                    WHEN $4 IS NOT NULL THEN google_ml.embedding($4)
                    ELSE embedding
                END,
                location = CASE
                    WHEN $5 IS NOT NULL AND $6 IS NOT NULL
                        THEN ST_MakePoint($5, $6)::geography
                    ELSE location
                END,
                municipality = COALESCE($7, municipality),
                updated_at = now()
            WHERE resource_id = $1
        """
        # プレースホルダ $1=resource_id, $2=name, $3=category, $4=description,
        # $5=longitude, $6=latitude, $7=municipality
        longitude = location.longitude if location is not None else None
        latitude = location.latitude if location is not None else None
        await self._pool.execute(
            query,
            resource_id,
            name,
            category,
            description,
            longitude,
            latitude,
            municipality,
        )

    async def delete(self, resource_id: UUID) -> None:
        """指定した地域資源を削除する（パラメータ化クエリ）。"""
        await self._pool.execute(
            "DELETE FROM regional_resources WHERE resource_id = $1", resource_id
        )


def _row_to_resource(row: Any) -> RegionalResource:
    """`asyncpg`が返す行データ（`asyncpg.Record`）を`RegionalResource`に変換する。

    Args:
        row: `asyncpg.Record`相当の行データ（`Mapping`インターフェースを持つ）。

    Returns:
        変換された`RegionalResource`。
    """
    return RegionalResource(
        resource_id=row["resource_id"],
        name=row["name"],
        category=row["category"],
        description=row["description"],
        location=GeoPoint(latitude=row["latitude"], longitude=row["longitude"]),
        file_url=row["file_url"],
        embedding=list(row["embedding"]) if row["embedding"] is not None else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        municipality=row["municipality"] if "municipality" in row else "",
    )

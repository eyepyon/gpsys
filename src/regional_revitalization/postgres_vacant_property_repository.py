"""Cloud SQL for PostgreSQL用`VacantPropertyRepository`実装のスケルトン。

`design.md`の「コンポーネント5: 居抜き物件同期サービス
(VacantPropertySyncService)」および「コンポーネント3」の
`vacant_property_candidates`テーブルDDLに基づき、`asyncpg`を用いた
PostgreSQL実装を提供する。

**SQLインジェクション対策の方針（Requirements 12.2）**:
`postgres_repository.py`（`PostgresResourceRepository`）と同様、すべてのクエリは
文字列連結でSQLを組み立てず、`asyncpg`のプレースホルダ（`$1`, `$2`, ...）による
パラメータ化クエリとして構築する。ユーザー入力（`place_id`, `name`, `types`等）は
SQL文字列に直接埋め込まれることなく、常にパラメータとして渡される。

**注意**: 本モジュールは実際のDB接続を行わないコード構造のみのスケルトンである。
接続文字列やコネクションプール（`asyncpg.Pool`）はコンストラクタで受け取る想定とし、
実際の接続確立・トランザクション管理は呼び出し側（アプリ起動処理等）の責務とする。
`asyncpg`が実行環境にインストールされていない場合でも本モジュールの読み込み自体が
失敗しないよう、importは`try/except ImportError`で保護し型ヒントのみに留める。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from regional_revitalization.models import GeoPoint
from regional_revitalization.vacant_property import (
    BusinessStatus,
    VacantPropertyCandidate,
)

if TYPE_CHECKING:
    # 型チェック時のみ`asyncpg`を参照する。実行時に未インストールでも
    # importエラーにならないようにするため、型ヒント専用の参照に留める。
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover - テスト環境に`asyncpg`が無い場合を想定
    _asyncpg = None


class PostgresVacantPropertyRepository:
    """Cloud SQL for PostgreSQL（PostGIS拡張）をバックエンドとする

    `VacantPropertyRepository`実装。

    `regional_revitalization.vacant_property.VacantPropertyRepository`
    （Protocol）を満たす。すべてのクエリはプレースホルダ（`$1`, `$2`, ...）で
    パラメータ化しており、ユーザー入力を文字列連結でSQLに埋め込むことはない
    （Requirements 12.2）。
    """

    def __init__(self, pool: "asyncpg.Pool") -> None:
        """コネクションプールを受け取って初期化する。

        Args:
            pool: `asyncpg.create_pool(...)`等で生成済みのコネクションプール。
                本クラスは接続確立自体は行わず、呼び出し側が用意したプールを
                受け取るだけである。
        """
        self._pool = pool

    async def upsert_by_place_id(self, candidate: VacantPropertyCandidate) -> None:
        """`place_id`をキーとしたUPSERT（`ON CONFLICT (place_id) DO UPDATE`）で

        居抜き物件候補を保存/更新する（パラメータ化クエリ）。

        既存レコードが存在すれば`name`, `location`, `business_status`, `types`
        等の全カラムを更新し、`updated_at`を現在時刻に更新する。存在しなければ
        新規作成する。これにより同一`place_id`について本メソッドを複数回呼び出しても、
        `vacant_property_candidates`テーブル内の該当レコードは常に1件のみに保たれる
        （Requirements 13.2）。

        Args:
            candidate: UPSERT対象の居抜き物件候補。
        """
        query = """
            INSERT INTO vacant_property_candidates (
                place_id, name, location, business_status, types,
                address, phone_number, data_fetched_at, last_review_time,
                estimated_closure_period_start, estimated_closure_period_end,
                updated_at
            ) VALUES (
                $1, $2, ST_MakePoint($3, $4)::geography, $5, $6,
                $7, $8, $9, $10,
                $11, $12,
                now()
            )
            ON CONFLICT (place_id) DO UPDATE SET
                name = EXCLUDED.name,
                location = EXCLUDED.location,
                business_status = EXCLUDED.business_status,
                types = EXCLUDED.types,
                address = EXCLUDED.address,
                phone_number = EXCLUDED.phone_number,
                data_fetched_at = EXCLUDED.data_fetched_at,
                last_review_time = EXCLUDED.last_review_time,
                estimated_closure_period_start = EXCLUDED.estimated_closure_period_start,
                estimated_closure_period_end = EXCLUDED.estimated_closure_period_end,
                updated_at = now()
        """
        # プレースホルダ $1=place_id, $2=name, $3=longitude, $4=latitude,
        # $5=business_status, $6=types, $7=address, $8=phone_number,
        # $9=data_fetched_at, $10=last_review_time,
        # $11=estimated_closure_period_start, $12=estimated_closure_period_end
        # place_id/name/address等のユーザー入力は文字列連結せず、常に
        # パラメータとして渡すためSQLインジェクションの余地がない。
        await self._pool.execute(
            query,
            candidate.place_id,
            candidate.name,
            candidate.location.longitude,
            candidate.location.latitude,
            candidate.business_status.value,
            candidate.types,
            candidate.address,
            candidate.phone_number,
            candidate.data_fetched_at,
            candidate.last_review_time,
            candidate.estimated_closure_period_start,
            candidate.estimated_closure_period_end,
        )

    async def search_by_business_status_and_type(
        self,
        location: GeoPoint,
        radius_km: float,
        business_status: BusinessStatus,
        types: list[str] | None,
        limit: int,
    ) -> list[VacantPropertyCandidate]:
        """`ST_DWithin`による地理的絞り込み、`business_status`一致、`types`配列の

        重なり判定（`&&`演算子）を単一SQLクエリで組み合わせて実行する
        （パラメータ化クエリ）。データベースに対する読み取り専用の操作であり、
        データを変更しない（Requirements 15.6）。

        Args:
            location: 検索基準となる位置情報。
            radius_km: 検索半径（キロメートル）。
            business_status: 絞り込み対象の営業状態。
            types: 業種・ジャンルタグによる絞り込み条件。Noneの場合は
                タグによる絞り込みを行わない。
            limit: 取得件数の上限。

        Returns:
            条件に合致する居抜き物件候補のリスト（距離の昇順、`limit`件以下）。
        """
        query = """
            SELECT
                place_id, name,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                business_status, types, address, phone_number,
                data_fetched_at, last_review_time,
                estimated_closure_period_start, estimated_closure_period_end
            FROM vacant_property_candidates
            WHERE ST_DWithin(
                location,
                ST_MakePoint($1, $2)::geography,
                $3
            )
            AND business_status = $4
            AND ($5::text[] IS NULL OR types && $5::text[])
            ORDER BY location <-> ST_MakePoint($1, $2)::geography
            LIMIT $6
        """
        # プレースホルダ $1=longitude, $2=latitude, $3=radius_km(メートル換算),
        # $4=business_status, $5=types(Noneの場合はNULLとして渡す。
        # &&演算子によるTEXT[]の重なり判定でtypesフィルタを行う), $6=limit
        rows = await self._pool.fetch(
            query,
            location.longitude,
            location.latitude,
            radius_km * 1000.0,
            business_status.value,
            types,
            limit,
        )
        return [_row_to_candidate(row) for row in rows]


def _row_to_candidate(row: Any) -> VacantPropertyCandidate:
    """`asyncpg`が返す行データ（`asyncpg.Record`）を`VacantPropertyCandidate`に

    変換する。

    Args:
        row: `asyncpg.Record`相当の行データ（`Mapping`インターフェースを持つ）。

    Returns:
        変換された`VacantPropertyCandidate`。
    """
    return VacantPropertyCandidate(
        place_id=row["place_id"],
        name=row["name"],
        location=GeoPoint(latitude=row["latitude"], longitude=row["longitude"]),
        business_status=BusinessStatus(row["business_status"]),
        types=list(row["types"]) if row["types"] is not None else [],
        address=row["address"],
        phone_number=row["phone_number"],
        data_fetched_at=row["data_fetched_at"],
        last_review_time=row["last_review_time"],
        estimated_closure_period_start=row["estimated_closure_period_start"],
        estimated_closure_period_end=row["estimated_closure_period_end"],
    )

"""Cloud SQL for PostgreSQL用`SearchRequestRepository`実装。

`search_requests`テーブル（`migrations/003_search_and_property_details.sql`）を
バックエンドとする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from regional_revitalization.models import GeoPoint
from regional_revitalization.search_history import SearchRequest
from regional_revitalization.vacant_property import BusinessStatus

if TYPE_CHECKING:
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover
    _asyncpg = None


class PostgresSearchRequestRepository:
    """Cloud SQL for PostgreSQLをバックエンドとする検索リクエスト履歴リポジトリ。"""

    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def insert(self, request: SearchRequest) -> UUID:
        query = """
            INSERT INTO search_requests (
                search_request_id, location, radius_km, business_status,
                types, result_count, created_at
            ) VALUES (
                $1, ST_MakePoint($2, $3)::geography, $4, $5, $6, $7, $8
            )
            RETURNING search_request_id
        """
        row = await self._pool.fetchrow(
            query,
            request.search_request_id,
            request.location.longitude,
            request.location.latitude,
            request.radius_km,
            request.business_status.value if request.business_status else None,
            request.types,
            request.result_count,
            request.created_at,
        )
        return row["search_request_id"]

    async def list_recent(self, limit: int) -> list[SearchRequest]:
        query = """
            SELECT
                search_request_id,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                radius_km, business_status, types, result_count, created_at
            FROM search_requests
            ORDER BY created_at DESC
            LIMIT $1
        """
        rows = await self._pool.fetch(query, limit)
        return [_row_to_request(row) for row in rows]

    async def get_by_id(self, search_request_id: UUID) -> SearchRequest | None:
        query = """
            SELECT
                search_request_id,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                radius_km, business_status, types, result_count, created_at
            FROM search_requests
            WHERE search_request_id = $1
        """
        row = await self._pool.fetchrow(query, search_request_id)
        return _row_to_request(row) if row is not None else None


def _row_to_request(row: Any) -> SearchRequest:
    return SearchRequest(
        search_request_id=row["search_request_id"],
        location=GeoPoint(latitude=row["latitude"], longitude=row["longitude"]),
        radius_km=row["radius_km"],
        business_status=(
            BusinessStatus(row["business_status"])
            if row["business_status"] is not None
            else None
        ),
        types=list(row["types"]) if row["types"] is not None else None,
        result_count=row["result_count"],
        created_at=row["created_at"],
    )

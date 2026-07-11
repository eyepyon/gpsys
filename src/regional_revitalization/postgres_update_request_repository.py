"""Cloud SQL for PostgreSQL用`UpdateRequestRepository`実装。

`resource_update_requests`テーブル（`migrations/002_admin_schema.sql`）を
バックエンドとする。`requested_changes`はJSONB列にマッピングし、
`asyncpg`が返すJSON文字列をPython辞書にデコードする。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from datetime import datetime

from regional_revitalization.update_request import UpdateRequest

if TYPE_CHECKING:
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover
    _asyncpg = None


class PostgresUpdateRequestRepository:
    """Cloud SQL for PostgreSQLをバックエンドとする更新依頼リポジトリ。"""

    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def insert(self, request: UpdateRequest) -> UUID:
        query = """
            INSERT INTO resource_update_requests (
                request_id, target_resource_id, requester_contact,
                requested_changes, message, status, reviewed_by_admin_id,
                reviewed_at, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING request_id
        """
        row = await self._pool.fetchrow(
            query,
            request.request_id,
            request.target_resource_id,
            request.requester_contact,
            json.dumps(request.requested_changes),
            request.message,
            request.status,
            request.reviewed_by_admin_id,
            request.reviewed_at,
            request.created_at,
            request.updated_at,
        )
        return row["request_id"]

    async def get_by_id(self, request_id: UUID) -> UpdateRequest | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM resource_update_requests WHERE request_id = $1",
            request_id,
        )
        return _row_to_request(row) if row is not None else None

    async def list_by_status(self, status: str | None) -> list[UpdateRequest]:
        if status is not None:
            rows = await self._pool.fetch(
                """
                SELECT * FROM resource_update_requests
                WHERE status = $1
                ORDER BY created_at DESC
                """,
                status,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM resource_update_requests ORDER BY created_at DESC"
            )
        return [_row_to_request(row) for row in rows]

    async def update_status(
        self,
        request_id: UUID,
        status: str,
        reviewed_by_admin_id: UUID,
        reviewed_at: datetime,
    ) -> None:
        query = """
            UPDATE resource_update_requests
            SET status = $2, reviewed_by_admin_id = $3, reviewed_at = $4, updated_at = $4
            WHERE request_id = $1
        """
        await self._pool.execute(
            query, request_id, status, reviewed_by_admin_id, reviewed_at
        )


def _row_to_request(row: Any) -> UpdateRequest:
    changes = row["requested_changes"]
    if isinstance(changes, str):
        changes = json.loads(changes)
    return UpdateRequest(
        request_id=row["request_id"],
        target_resource_id=row["target_resource_id"],
        requester_contact=row["requester_contact"],
        requested_changes=changes,
        message=row["message"],
        status=row["status"],
        reviewed_by_admin_id=row["reviewed_by_admin_id"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

"""Cloud SQL for PostgreSQL用`AdminUserRepository`実装。

`regional_revitalization.postgres_repository`と同様のパターン
（`asyncpg`のプレースホルダによるパラメータ化クエリ、非同期メソッド）に従う。

**注意**: `AdminUserRepository` Protocol（`admin_auth.py`）は同期メソッドとして
定義されているが、本実装は`asyncpg`を使うため非同期メソッドとして提供する。
呼び出し側（FastAPIエンドポイント）は本クラスを直接非同期に呼び出す想定であり、
Protocol自体は同期I/Oのインメモリ実装（テスト用）との互換性のために同期定義のままとする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from regional_revitalization.admin_auth import AdminSession, AdminUser

if TYPE_CHECKING:
    import asyncpg

try:
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover - テスト環境に`asyncpg`が無い場合を想定
    _asyncpg = None


class PostgresAdminUserRepository:
    """Cloud SQL for PostgreSQLをバックエンドとする管理ユーザー・セッションリポジトリ。"""

    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def get_by_username(self, username: str) -> AdminUser | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM admin_users WHERE username = $1", username
        )
        return _row_to_user(row) if row is not None else None

    async def get_by_id(self, admin_user_id: UUID) -> AdminUser | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM admin_users WHERE admin_user_id = $1", admin_user_id
        )
        return _row_to_user(row) if row is not None else None

    async def list_all(self) -> list[AdminUser]:
        rows = await self._pool.fetch(
            "SELECT * FROM admin_users ORDER BY created_at ASC"
        )
        return [_row_to_user(row) for row in rows]

    async def count(self) -> int:
        row = await self._pool.fetchrow("SELECT COUNT(*) AS c FROM admin_users")
        return int(row["c"])

    async def insert(self, user: AdminUser) -> UUID:
        query = """
            INSERT INTO admin_users (
                admin_user_id, username, password_hash, display_name,
                role, is_active, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING admin_user_id
        """
        row = await self._pool.fetchrow(
            query,
            user.admin_user_id,
            user.username,
            user.password_hash,
            user.display_name,
            user.role,
            user.is_active,
            user.created_at,
            user.updated_at,
        )
        return row["admin_user_id"]

    async def update(
        self,
        admin_user_id: UUID,
        display_name: str | None,
        password_hash: str | None,
        is_active: bool | None,
    ) -> None:
        query = """
            UPDATE admin_users
            SET
                display_name = COALESCE($2, display_name),
                password_hash = COALESCE($3, password_hash),
                is_active = COALESCE($4, is_active),
                updated_at = now()
            WHERE admin_user_id = $1
        """
        await self._pool.execute(
            query, admin_user_id, display_name, password_hash, is_active
        )

    async def delete(self, admin_user_id: UUID) -> None:
        await self._pool.execute(
            "DELETE FROM admin_users WHERE admin_user_id = $1", admin_user_id
        )

    async def create_session(self, session: AdminSession) -> None:
        query = """
            INSERT INTO admin_sessions (session_token, admin_user_id, expires_at, created_at)
            VALUES ($1, $2, $3, $4)
        """
        await self._pool.execute(
            query,
            session.session_token,
            session.admin_user_id,
            session.expires_at,
            session.created_at,
        )

    async def get_session(self, session_token: str) -> AdminSession | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM admin_sessions WHERE session_token = $1", session_token
        )
        if row is None:
            return None
        return AdminSession(
            session_token=row["session_token"],
            admin_user_id=row["admin_user_id"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    async def delete_session(self, session_token: str) -> None:
        await self._pool.execute(
            "DELETE FROM admin_sessions WHERE session_token = $1", session_token
        )


def _row_to_user(row: Any) -> AdminUser:
    return AdminUser(
        admin_user_id=row["admin_user_id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

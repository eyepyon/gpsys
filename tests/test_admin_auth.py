"""管理ユーザー認証・セッション管理モジュール（admin_auth.py）の単体テスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from regional_revitalization.admin_auth import (
    AdminSession,
    InMemoryAdminUserRepository,
    authenticate,
    create_admin_user,
    hash_password,
    resolve_session,
    verify_password,
)


class TestPasswordHashing:
    def test_verify_password_succeeds_for_correct_password(self) -> None:
        hashed = hash_password("correct-password-123")
        assert verify_password("correct-password-123", hashed) is True

    def test_verify_password_fails_for_incorrect_password(self) -> None:
        hashed = hash_password("correct-password-123")
        assert verify_password("wrong-password", hashed) is False

    def test_verify_password_returns_false_for_malformed_hash(self) -> None:
        assert verify_password("anything", "not-a-valid-hash") is False

    def test_hash_password_is_nondeterministic(self) -> None:
        # ソルトがランダムなため、同一パスワードでも異なるハッシュ文字列になる。
        assert hash_password("same-password") != hash_password("same-password")


class TestCreateAdminUser:
    @pytest.mark.asyncio
    async def test_creates_user_with_hashed_password(self) -> None:
        repo = InMemoryAdminUserRepository()
        user = await create_admin_user(repo, "alice", "password123", "Alice")
        assert user.username == "alice"
        assert user.display_name == "Alice"
        assert user.role == "full_admin"
        assert user.is_active is True
        assert verify_password("password123", user.password_hash)

    @pytest.mark.asyncio
    async def test_rejects_duplicate_username(self) -> None:
        repo = InMemoryAdminUserRepository()
        await create_admin_user(repo, "alice", "password123", "Alice")
        with pytest.raises(ValueError, match="既に使用されています"):
            await create_admin_user(repo, "alice", "password456", "Alice2")

    @pytest.mark.asyncio
    async def test_rejects_short_password(self) -> None:
        repo = InMemoryAdminUserRepository()
        with pytest.raises(ValueError, match="8文字以上"):
            await create_admin_user(repo, "alice", "short", "Alice")


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_succeeds_with_correct_credentials(self) -> None:
        repo = InMemoryAdminUserRepository()
        await create_admin_user(repo, "alice", "password123", "Alice")
        session = await authenticate(repo, "alice", "password123")
        assert session.admin_user_id is not None
        assert len(session.session_token) > 0

    @pytest.mark.asyncio
    async def test_fails_with_wrong_password(self) -> None:
        repo = InMemoryAdminUserRepository()
        await create_admin_user(repo, "alice", "password123", "Alice")
        with pytest.raises(ValueError, match="正しくありません"):
            await authenticate(repo, "alice", "wrong-password")

    @pytest.mark.asyncio
    async def test_fails_with_unknown_username(self) -> None:
        repo = InMemoryAdminUserRepository()
        with pytest.raises(ValueError, match="正しくありません"):
            await authenticate(repo, "unknown", "password123")

    @pytest.mark.asyncio
    async def test_fails_for_deactivated_user(self) -> None:
        repo = InMemoryAdminUserRepository()
        user = await create_admin_user(repo, "alice", "password123", "Alice")
        await repo.update(user.admin_user_id, None, None, False)
        with pytest.raises(ValueError, match="正しくありません"):
            await authenticate(repo, "alice", "password123")


class TestResolveSession:
    @pytest.mark.asyncio
    async def test_resolves_valid_session(self) -> None:
        repo = InMemoryAdminUserRepository()
        await create_admin_user(repo, "alice", "password123", "Alice")
        session = await authenticate(repo, "alice", "password123")
        resolved = await resolve_session(repo, session.session_token)
        assert resolved.username == "alice"

    @pytest.mark.asyncio
    async def test_fails_for_unknown_token(self) -> None:
        repo = InMemoryAdminUserRepository()
        with pytest.raises(ValueError, match="セッションが無効"):
            await resolve_session(repo, "nonexistent-token")

    @pytest.mark.asyncio
    async def test_fails_for_expired_session(self) -> None:
        repo = InMemoryAdminUserRepository()
        user = await create_admin_user(repo, "alice", "password123", "Alice")
        expired_session = AdminSession(
            session_token="expired-token",
            admin_user_id=user.admin_user_id,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await repo.create_session(expired_session)
        with pytest.raises(ValueError, match="有効期限が切れました"):
            await resolve_session(repo, "expired-token")

"""管理画面向けの管理ユーザー認証・セッション管理モジュール。

管理画面（フロント画面inukiの`/admin/`配下）向けに、以下を実装する。

- `AdminUser`: 管理ユーザーのデータモデル。現状はフル管理者権限のみ運用するが、
  将来の権限分離に備えて`role`列を保持する。
- `AdminSession`: ログインセッション（トークン・有効期限）のデータモデル。
- パスワードハッシュ化ユーティリティ（PBKDF2-HMAC-SHA256、ソルト付き）。
  外部ライブラリ（bcrypt等）への依存を増やさず、標準ライブラリ`hashlib`のみで
  実装する。
- `AdminUserRepository` Protocol: 管理ユーザー・セッションの永続化インターフェース。
- `InMemoryAdminUserRepository`: テスト・ローカル開発用のインメモリ実装。

**セッション方式について**: JWTの自己署名検証ではなく、DBに保存したランダムな
セッショントークンをそのままAPIキー的に扱う方式とする。これにより、
ログアウト・強制失効がDELETE一発で可能になり、署名鍵の管理も不要になる。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

# PBKDF2-HMAC-SHA256の反復回数。NIST SP 800-63Bの推奨に基づき、
# 現実的な検証時間（数十ミリ秒程度）を保ちつつ十分な強度を確保する。
PBKDF2_ITERATIONS = 600_000

# パスワードハッシュ生成時に使用するソルトの長さ（バイト）。
SALT_LENGTH_BYTES = 16

# セッショントークンの長さ（バイト、`secrets.token_urlsafe`に渡す値）。
SESSION_TOKEN_LENGTH_BYTES = 32

# ログインセッションの有効期限（デフォルト: 12時間）。
DEFAULT_SESSION_TTL = timedelta(hours=12)

# 現状運用する唯一のロール値（フル管理者）。将来の権限分離に備えて
# `AdminUser.role`列自体は用意しておくが、値のバリデーションはこの1種類のみ行う。
ROLE_FULL_ADMIN = "full_admin"


def hash_password(plain_password: str) -> str:
    """平文パスワードをPBKDF2-HMAC-SHA256でハッシュ化する。

    ソルトはランダム生成し、`"<ソルトのhex>$<ハッシュのhex>"`形式の1文字列として
    返す。この文字列をそのまま`AdminUser.password_hash`に保存する。

    Args:
        plain_password: 平文パスワード。

    Returns:
        `"<ソルトのhex>$<ハッシュのhex>"`形式の文字列。
    """
    salt = secrets.token_bytes(SALT_LENGTH_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, password_hash: str) -> bool:
    """平文パスワードが`password_hash`（`hash_password()`の出力形式）と一致するか検証する。

    タイミング攻撃を避けるため、比較は`hmac.compare_digest`を使用する。

    Args:
        plain_password: 検証対象の平文パスワード。
        password_hash: `hash_password()`が生成した`"<ソルト>$<ハッシュ>"`形式の文字列。

    Returns:
        一致する場合True。`password_hash`の形式が不正な場合もFalseを返す
        （例外を発生させない）。
    """
    try:
        salt_hex, hash_hex = password_hash.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(derived, expected)


def generate_session_token() -> str:
    """暗号論的に安全なランダムセッショントークンを生成する。"""
    return secrets.token_urlsafe(SESSION_TOKEN_LENGTH_BYTES)


@dataclass(frozen=True)
class AdminUser:
    """管理ユーザー。

    Attributes:
        admin_user_id: 一意識別子。
        username: ログインID（一意）。空文字列は不可。
        password_hash: `hash_password()`が生成したハッシュ文字列。
        display_name: 管理画面上に表示する名前。
        role: 権限ロール。現状は`ROLE_FULL_ADMIN`固定で運用する
            （将来の権限分離に備えた列であり、現時点では値の種類を増やさない）。
        is_active: 無効化されたアカウントはFalse。ログイン不可になる。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    admin_user_id: UUID
    username: str
    password_hash: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.username == "":
            raise ValueError("usernameは空文字列であってはなりません")
        if self.display_name == "":
            raise ValueError("display_nameは空文字列であってはなりません")


@dataclass(frozen=True)
class AdminSession:
    """管理ユーザーのログインセッション。

    Attributes:
        session_token: セッショントークン（一意、認証時のキー）。
        admin_user_id: このセッションを所有する管理ユーザーのID。
        expires_at: 有効期限。この時刻以降は失効扱いとする。
        created_at: 作成日時。
    """

    session_token: str
    admin_user_id: UUID
    expires_at: datetime
    created_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        """現在時刻（省略時は`datetime.now(timezone.utc)`）を基準に有効期限切れか判定する。"""
        current = now if now is not None else datetime.now(timezone.utc)
        return current >= self.expires_at


class AdminUserRepository(Protocol):
    """管理ユーザー・セッションの永続化リポジトリ（Cloud SQLをバックエンドとする）。

    Cloud SQL実装（`asyncpg`）に合わせ、全メソッドを非同期(`async def`)として
    定義する。テスト用の`InMemoryAdminUserRepository`もこれに合わせて
    非同期メソッドとして実装する（内部処理自体は同期だがawait可能にする）。
    """

    async def get_by_username(self, username: str) -> AdminUser | None:
        """`username`に一致する管理ユーザーを返す。存在しない場合はNoneを返す。"""
        ...

    async def get_by_id(self, admin_user_id: UUID) -> AdminUser | None:
        """`admin_user_id`に一致する管理ユーザーを返す。存在しない場合はNoneを返す。"""
        ...

    async def list_all(self) -> list[AdminUser]:
        """全管理ユーザーを作成日時の昇順で返す。"""
        ...

    async def count(self) -> int:
        """管理ユーザーの総数を返す（初回起動時のブートストラップ判定に使用する）。"""
        ...

    async def insert(self, user: AdminUser) -> UUID:
        """管理ユーザーを登録し、`admin_user_id`を返す。"""
        ...

    async def update(
        self,
        admin_user_id: UUID,
        display_name: str | None,
        password_hash: str | None,
        is_active: bool | None,
    ) -> None:
        """指定した管理ユーザーの属性を更新する。`None`が渡された項目は変更しない。"""
        ...

    async def delete(self, admin_user_id: UUID) -> None:
        """管理ユーザーを削除する（関連するセッションもカスケード削除される）。"""
        ...

    async def create_session(self, session: AdminSession) -> None:
        """ログインセッションを登録する。"""
        ...

    async def get_session(self, session_token: str) -> AdminSession | None:
        """`session_token`に一致するセッションを返す。存在しない場合はNoneを返す。"""
        ...

    async def delete_session(self, session_token: str) -> None:
        """指定したセッションを削除する（ログアウト処理）。"""
        ...


class InMemoryAdminUserRepository:
    """テスト・ローカル開発用のインメモリ`AdminUserRepository`実装。

    内部処理自体は同期だが、Postgres実装とインターフェースを揃えるため
    全メソッドを`async def`として実装する。
    """

    def __init__(self, users: list[AdminUser] | None = None) -> None:
        self._users_by_id: dict[UUID, AdminUser] = {}
        self._sessions_by_token: dict[str, AdminSession] = {}
        if users:
            for user in users:
                self._users_by_id[user.admin_user_id] = user

    async def get_by_username(self, username: str) -> AdminUser | None:
        for user in self._users_by_id.values():
            if user.username == username:
                return user
        return None

    async def get_by_id(self, admin_user_id: UUID) -> AdminUser | None:
        return self._users_by_id.get(admin_user_id)

    async def list_all(self) -> list[AdminUser]:
        return sorted(self._users_by_id.values(), key=lambda u: u.created_at)

    async def count(self) -> int:
        return len(self._users_by_id)

    async def insert(self, user: AdminUser) -> UUID:
        self._users_by_id[user.admin_user_id] = user
        return user.admin_user_id

    async def update(
        self,
        admin_user_id: UUID,
        display_name: str | None,
        password_hash: str | None,
        is_active: bool | None,
    ) -> None:
        existing = self._users_by_id.get(admin_user_id)
        if existing is None:
            raise ValueError(f"管理ユーザーが見つかりません: {admin_user_id}")
        updated = AdminUser(
            admin_user_id=existing.admin_user_id,
            username=existing.username,
            password_hash=password_hash if password_hash is not None else existing.password_hash,
            display_name=display_name if display_name is not None else existing.display_name,
            role=existing.role,
            is_active=is_active if is_active is not None else existing.is_active,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._users_by_id[admin_user_id] = updated

    async def delete(self, admin_user_id: UUID) -> None:
        self._users_by_id.pop(admin_user_id, None)
        stale_tokens = [
            token
            for token, session in self._sessions_by_token.items()
            if session.admin_user_id == admin_user_id
        ]
        for token in stale_tokens:
            del self._sessions_by_token[token]

    async def create_session(self, session: AdminSession) -> None:
        self._sessions_by_token[session.session_token] = session

    async def get_session(self, session_token: str) -> AdminSession | None:
        return self._sessions_by_token.get(session_token)

    async def delete_session(self, session_token: str) -> None:
        self._sessions_by_token.pop(session_token, None)


async def create_admin_user(
    repository: AdminUserRepository,
    username: str,
    plain_password: str,
    display_name: str,
) -> AdminUser:
    """新規管理ユーザーを作成する。

    Args:
        repository: 登録先のリポジトリ。
        username: ログインID（既存ユーザーと重複しないこと）。
        plain_password: 平文パスワード（8文字以上であること）。
        display_name: 表示名。

    Returns:
        作成された`AdminUser`。

    Raises:
        ValueError: `username`が既に使用されている場合、または
            `plain_password`が8文字未満の場合。
    """
    if len(plain_password) < 8:
        raise ValueError("パスワードは8文字以上である必要があります")
    if await repository.get_by_username(username) is not None:
        raise ValueError(f"このユーザー名は既に使用されています: {username}")

    now = datetime.now(timezone.utc)
    user = AdminUser(
        admin_user_id=uuid4(),
        username=username,
        password_hash=hash_password(plain_password),
        display_name=display_name,
        role=ROLE_FULL_ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    await repository.insert(user)
    return user


async def authenticate(
    repository: AdminUserRepository, username: str, plain_password: str
) -> AdminSession:
    """ユーザー名・パスワードで認証し、成功時はログインセッションを発行する。

    Args:
        repository: 認証対象のリポジトリ。
        username: ログインID。
        plain_password: 平文パスワード。

    Returns:
        新規作成された`AdminSession`。

    Raises:
        ValueError: ユーザーが存在しない、無効化されている、またはパスワードが
            一致しない場合。エラーメッセージはユーザー名の存在有無を区別せず
            同一の文言とし、ユーザー名の存在確認（列挙攻撃）を防ぐ。
    """
    invalid_message = "ユーザー名またはパスワードが正しくありません"
    user = await repository.get_by_username(username)
    if user is None or not user.is_active:
        raise ValueError(invalid_message)
    if not verify_password(plain_password, user.password_hash):
        raise ValueError(invalid_message)

    now = datetime.now(timezone.utc)
    session = AdminSession(
        session_token=generate_session_token(),
        admin_user_id=user.admin_user_id,
        expires_at=now + DEFAULT_SESSION_TTL,
        created_at=now,
    )
    await repository.create_session(session)
    return session


async def resolve_session(
    repository: AdminUserRepository, session_token: str
) -> AdminUser:
    """セッショントークンから、有効なログイン中の管理ユーザーを解決する。

    Args:
        repository: セッション・ユーザーを検索するリポジトリ。
        session_token: `Authorization: Bearer <token>`ヘッダー等から取得したトークン。

    Returns:
        認証済みの`AdminUser`。

    Raises:
        ValueError: セッションが存在しない、期限切れ、対象ユーザーが存在しない、
            または無効化されている場合。
    """
    session = await repository.get_session(session_token)
    if session is None:
        raise ValueError("セッションが無効です。再度ログインしてください")
    if session.is_expired():
        await repository.delete_session(session_token)
        raise ValueError("セッションの有効期限が切れました。再度ログインしてください")

    user = await repository.get_by_id(session.admin_user_id)
    if user is None or not user.is_active:
        raise ValueError("セッションが無効です。再度ログインしてください")
    return user

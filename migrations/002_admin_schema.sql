-- 地方創生支援システム: 管理画面用スキーマ追加（マイグレーションスクリプト）
--
-- 管理画面（フロント画面inuki配下の /admin/）向けに以下を追加する。
--   - admin_users テーブル（管理ユーザー。現状はフル管理者権限のみだが、
--     将来の権限分離に備えて role 列を用意しておく）
--   - admin_sessions テーブル（ログインセッション管理。JWTの自己署名検証では
--     なく、DBに保存したランダムトークンをセッションIDとして扱う方式とする。
--     これにより、トークンの即時無効化（ログアウト・強制失効）がDELETE一発で
--     可能になる）
--   - resource_update_requests テーブル（利用者からの地域資源データ更新依頼。
--     申請内容をJSONBで保持し、承認/却下のワークフローに対応する）
--   - regional_resources.municipality 列（市町村別統計のための追加列。
--     既存データは空文字列のままとなるため、統計では「未設定」として扱う）
--
-- 実行方法（例）:
--   psql "$DATABASE_URL" -f migrations/002_admin_schema.sql
--
-- 本ファイルはUTF-8・LF改行で保存する。

-- ============================================================
-- テーブル: admin_users（管理ユーザー）
-- ============================================================

CREATE TABLE IF NOT EXISTS admin_users (
    admin_user_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT UNIQUE NOT NULL,
    -- PBKDF2-HMAC-SHA256によるパスワードハッシュ（ソルト込みの1文字列として保存）。
    -- 平文パスワードはいかなる場所にも保存しない。
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    -- 現状はフル管理者権限のみ運用するが、将来の権限分離に備えて列を用意する。
    -- 値は "full_admin"（フル管理者）固定で運用開始する。
    role            TEXT NOT NULL DEFAULT 'full_admin',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- テーブル: admin_sessions（ログインセッション）
-- ============================================================
-- session_token自体はアプリ側で生成した暗号論的に安全なランダム文字列。
-- ハッシュ化せずそのまま保存する（DB自体がSecret Manager経由の認証情報で
-- 保護されたプライベートIP接続のみのため、Cookie/Authorizationヘッダーの
-- 値としてそのまま検索キーに使う設計とする）。

CREATE TABLE IF NOT EXISTS admin_sessions (
    session_token   TEXT PRIMARY KEY,
    admin_user_id   UUID NOT NULL REFERENCES admin_users(admin_user_id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_admin_user_id ON admin_sessions
    (admin_user_id);

-- ============================================================
-- テーブル: resource_update_requests（データ更新依頼）
-- ============================================================
-- 利用者から寄せられた地域資源データの更新依頼を保持する。
-- 対象がまだ存在しない新規登録提案の場合もあるため、target_resource_idは
-- NULL可とする（NULLの場合は新規登録の提案として扱う）。

CREATE TABLE IF NOT EXISTS resource_update_requests (
    request_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_resource_id  UUID NULL REFERENCES regional_resources(resource_id) ON DELETE SET NULL,
    -- 依頼者情報（会員登録機能が無いため自由記述の連絡先文字列として保持する）
    requester_contact    TEXT NULL,
    -- 依頼内容（提案する変更後の値をJSONBで保持する。例:
    -- {"name": "新名称", "description": "新説明文", "category": "新カテゴリ"}）
    requested_changes    JSONB NOT NULL,
    -- 依頼理由・補足メッセージ
    message               TEXT NULL,
    -- pending（未対応）/ approved（承認・反映済み）/ rejected（却下）
    status                 TEXT NOT NULL DEFAULT 'pending',
    -- 承認・却下を行った管理ユーザー（未対応の間はNULL）
    reviewed_by_admin_id   UUID NULL REFERENCES admin_users(admin_user_id) ON DELETE SET NULL,
    reviewed_at            TIMESTAMPTZ NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_update_requests_status ON resource_update_requests
    (status);
CREATE INDEX IF NOT EXISTS idx_update_requests_target_resource_id
    ON resource_update_requests (target_resource_id);

-- ============================================================
-- regional_resources: 市町村別統計用の列を追加
-- ============================================================
-- 既存データは空文字列で埋める（統計上は「未設定」として扱う）。
-- 将来的にジオコーディングによる自動入力、または管理画面での手動入力を想定する。

ALTER TABLE regional_resources
    ADD COLUMN IF NOT EXISTS municipality TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_resources_municipality ON regional_resources
    (municipality);

-- vacant_property_candidates側にも同様に市町村列を追加する
-- （address列はあるが自由記述のため、統計用に正規化した市町村名を別途持てるようにする）
ALTER TABLE vacant_property_candidates
    ADD COLUMN IF NOT EXISTS municipality TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_vacant_properties_municipality
    ON vacant_property_candidates (municipality);

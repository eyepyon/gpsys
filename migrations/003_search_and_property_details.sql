-- 地方創生支援システム: 検索履歴・物件詳細項目の追加（マイグレーションスクリプト）
--
-- 本マイグレーションでは以下を追加する。
--   - vacant_property_candidatesへの賃料・面積・築年数・構造カラム追加
--     （Places APIからは取得できないため、管理画面での手動編集専用の項目。
--     フロント（利用者向け画面）には表示しない）
--   - search_requestsテーブル（利用者の居抜き物件検索リクエストを常に記録する。
--     検索した場所・条件・表示できた件数を保存し、管理画面から「この場所で
--     Google Places APIをリアルタイム検索する」機能のトリガー元データとする）
--
-- 実行方法（例）:
--   psql "$DATABASE_URL" -f migrations/003_search_and_property_details.sql
--
-- 本ファイルはUTF-8・LF改行で保存する。

-- ============================================================
-- vacant_property_candidates: 賃料・面積・築年数・構造カラムの追加
-- ============================================================
-- Google Places APIからは取得できない情報のため、管理画面での手動入力
-- 専用の項目とする。既存データはすべてNULL（未入力）から開始する。

ALTER TABLE vacant_property_candidates
    ADD COLUMN IF NOT EXISTS rent_yen INTEGER NULL;
ALTER TABLE vacant_property_candidates
    ADD COLUMN IF NOT EXISTS area_sqm NUMERIC(10, 2) NULL;
ALTER TABLE vacant_property_candidates
    ADD COLUMN IF NOT EXISTS built_year INTEGER NULL;
ALTER TABLE vacant_property_candidates
    ADD COLUMN IF NOT EXISTS structure TEXT NULL;

-- ============================================================
-- テーブル: search_requests（利用者の検索リクエスト履歴）
-- ============================================================
-- 居抜き物件検索（POST /vacant-properties/search）が呼び出される度に、
-- 検索した場所・条件・表示できた件数を記録する。管理画面から、この履歴
-- 一覧の各行に対して「この場所でGoogle Places APIをリアルタイム検索する」
-- 操作を行える（`admin_search_executions`テーブル参照）。

CREATE TABLE IF NOT EXISTS search_requests (
    search_request_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location            GEOGRAPHY(POINT, 4326) NOT NULL,
    radius_km           DOUBLE PRECISION NOT NULL,
    business_status     TEXT NULL,
    types                TEXT[] NULL,
    result_count         INTEGER NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_requests_created_at ON search_requests
    (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_requests_location ON search_requests
    USING GIST (location);

-- ============================================================
-- テーブル: places_search_results（Places APIリアルタイム検索結果の一時保存）
-- ============================================================
-- 管理画面で「この場所でGoogle Places APIを検索する」を実行した結果を、
-- レビュー・登録待ちの状態で一時保存する。管理者が個別に確認し、
-- 「登録する」操作をした結果のみ、vacant_property_candidatesにUPSERTされる
-- （Places検索結果を無条件で自動登録しない。品質・コストの管理者による
-- 制御を維持するための設計）。

CREATE TABLE IF NOT EXISTS places_search_results (
    result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_request_id   UUID NULL REFERENCES search_requests(search_request_id) ON DELETE SET NULL,
    place_id            TEXT NOT NULL,
    name                 TEXT NOT NULL,
    location             GEOGRAPHY(POINT, 4326) NOT NULL,
    business_status      TEXT NOT NULL,
    types                 TEXT[] NOT NULL,
    address               TEXT NULL,
    phone_number          TEXT NULL,
    -- 管理者が「登録する」を押してvacant_property_candidatesに反映済みかどうか。
    is_registered          BOOLEAN NOT NULL DEFAULT false,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_places_search_results_search_request_id
    ON places_search_results (search_request_id);

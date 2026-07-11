-- 地方創生支援システム: 初期スキーマ定義（マイグレーションスクリプト）
--
-- `design.md`の「コンポーネント3: データストア (Cloud SQL for PostgreSQL)」に記載された
-- スキーマ概要（DDL相当）に基づき、Cloud SQL for PostgreSQL上に以下を構築する。
--   - PostGIS拡張（地理空間インデックス）
--   - pgvector拡張（ベクトルインデックス）
--   - google_ml_integration拡張（SQL関数呼び出しによるDB側embedding生成）
--   - regional_resources テーブル（地域資源メタデータ・位置情報・embedding）
--   - consultation_logs テーブル（相談履歴）
--
-- 対象: Requirements 4.1, 4.2, 4.3, 4.4, 8.1, 8.2, 8.3
--
-- 実行方法（例）:
--   psql "$DATABASE_URL" -f migrations/001_init_schema.sql
--
-- 本ファイルはUTF-8・LF改行で保存する。

-- ============================================================
-- 拡張機能の有効化
-- ============================================================

-- PostGIS拡張: 地理空間型（GEOGRAPHY）とGiSTインデックスによる近隣検索を可能にする
-- （Requirements 8.1）
CREATE EXTENSION IF NOT EXISTS postgis;

-- pgvector拡張: VECTOR型とHNSW/IVFFlatインデックスによる類似度検索を可能にする
-- （Requirements 8.2）
CREATE EXTENSION IF NOT EXISTS vector;

-- google_ml_integration拡張: SQL関数呼び出し（google_ml.embedding(...)相当）により
-- テキストのembeddingをDB側（Cloud SQL側）で生成するための拡張機能。
-- アプリケーション側では外部embeddingモデルの呼び出しを行わない方針
-- （design.md「embeddingに関する方針」参照）のため、本拡張を有効化する。
CREATE EXTENSION IF NOT EXISTS google_ml_integration;

-- ============================================================
-- テーブル: regional_resources（地域資源）
-- ============================================================
-- 地域資源メタデータ・位置情報（GEOGRAPHY）・embeddingベクトル（VECTOR(768)）を
-- 1つのテーブルで一貫して管理する（Requirements 8.1, 8.2）。

CREATE TABLE IF NOT EXISTS regional_resources (
    resource_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    description   TEXT NOT NULL,
    location      GEOGRAPHY(POINT, 4326) NOT NULL,
    file_url      TEXT NULL,
    -- embeddingはINSERT時にgoogle_ml.embedding(description)相当のSQL関数呼び出しで
    -- DB側から生成・格納する（アプリケーション側では生成しない）。
    embedding     VECTOR(768) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 地理空間インデックス（GiST）: search_nearby / search_hybrid のST_DWithin絞り込みを
-- 高速化する（Requirements 8.3）。
CREATE INDEX IF NOT EXISTS idx_resources_location ON regional_resources
    USING GIST (location);

-- ベクトルインデックス（HNSW, コサイン距離）: search_similar / search_hybrid の
-- `<=>`演算子によるソートを高速化する（Requirements 8.3）。
CREATE INDEX IF NOT EXISTS idx_resources_embedding ON regional_resources
    USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- テーブル: consultation_logs（相談履歴）
-- ============================================================
-- 相談リクエスト（質問文・位置情報）と、参照した地域資源・生成結果を記録する。

CREATE TABLE IF NOT EXISTS consultation_logs (
    log_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text              TEXT NOT NULL,
    query_location          GEOGRAPHY(POINT, 4326) NOT NULL,
    referenced_resource_ids UUID[] NOT NULL,
    generated_text          TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- テーブル: vacant_property_candidates（居抜き物件候補）
-- ============================================================
-- Places APIで検知した`CLOSED_PERMANENTLY`（完全閉店・廃業）スポットを
-- `place_id`をキーとしたUPSERTで保存/更新する（Requirements 13.2, 13.3）。

CREATE TABLE IF NOT EXISTS vacant_property_candidates (
    candidate_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- place_idはUNIQUE NOT NULL制約により、同一スポットの重複登録・再取得時の
    -- 同一性判定を保証する。UNIQUE制約により自動的に一意インデックスが作成される。
    place_id                      TEXT UNIQUE NOT NULL,
    name                          TEXT NOT NULL,
    location                      GEOGRAPHY(POINT, 4326) NOT NULL,
    -- OPERATIONAL / CLOSED_TEMPORARILY / CLOSED_PERMANENTLY のいずれか
    -- （アプリ側の`BusinessStatus` Enumで検証する）
    business_status               TEXT NOT NULL,
    -- 業種・ジャンルタグ配列。例: {restaurant, cafe}
    types                         TEXT[] NOT NULL,
    address                       TEXT NULL,
    phone_number                  TEXT NULL,
    data_fetched_at               TIMESTAMPTZ NOT NULL,
    last_review_time              TIMESTAMPTZ NULL,
    estimated_closure_period_start TIMESTAMPTZ NULL,
    estimated_closure_period_end   TIMESTAMPTZ NULL,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 地理空間インデックス（GiST）: search_by_business_status_and_type の
-- ST_DWithin絞り込みを高速化する（Requirements 15.2）。
CREATE INDEX IF NOT EXISTS idx_vacant_properties_location ON vacant_property_candidates
    USING GIST (location);

-- business_statusインデックス: business_status一致条件による絞り込みを
-- 高速化する（Requirements 15.3）。
CREATE INDEX IF NOT EXISTS idx_vacant_properties_business_status ON vacant_property_candidates
    (business_status);

-- 業種タグ配列インデックス（GIN）: types配列の重なり判定（&&演算子）による
-- 絞り込みを高速化する（Requirements 15.4）。
CREATE INDEX IF NOT EXISTS idx_vacant_properties_types ON vacant_property_candidates
    USING GIN (types);

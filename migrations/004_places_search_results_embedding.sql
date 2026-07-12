-- 地方創生支援システム: 全店舗データ（places_search_results）のベクトルDB化
--
-- 本マイグレーションでは以下を追加する。
--   - places_search_resultsへのembeddingカラム追加（VECTOR(768)）。
--     regional_resourcesと同様に、google_ml_integration拡張のSQL関数
--     （google_ml.embedding(...)）によりDB側でembeddingを生成する方針とする
--     （アプリケーション側では外部embeddingモデルの呼び出しを行わない）。
--     embedding生成元テキストは「店舗名 + 業種タグ + 住所」の連結とする。
--   - HNSWベクトルインデックス（コサイン距離）
--   - 既存行のバックフィル（embeddingが未生成の行のみ対象のため冪等。
--     本マイグレーションはアプリ起動時に毎回実行されるが、embedding未生成の
--     行が無ければ何も行わない）
--
-- 実行方法（例）:
--   psql "$DATABASE_URL" -f migrations/004_places_search_results_embedding.sql
--
-- 本ファイルはUTF-8・LF改行で保存する。

-- ============================================================
-- places_search_results: embeddingカラムの追加
-- ============================================================

ALTER TABLE places_search_results
    ADD COLUMN IF NOT EXISTS embedding VECTOR(768) NULL;

-- ベクトルインデックス（HNSW, コサイン距離）: 類似店舗検索・統計での
-- `<=>`演算子によるソートを高速化する。
CREATE INDEX IF NOT EXISTS idx_places_search_results_embedding
    ON places_search_results USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- 既存行のバックフィル（embedding未生成の行のみ）
-- ============================================================
-- 店舗名・業種タグ・住所を連結したテキストからembeddingを生成する。
-- WHERE embedding IS NULLにより、生成済みの行は再計算しない（冪等）。

UPDATE places_search_results
SET embedding = google_ml.embedding(
    name
    || ' ' || array_to_string(types, ' ')
    || COALESCE(' ' || address, '')
)
WHERE embedding IS NULL;

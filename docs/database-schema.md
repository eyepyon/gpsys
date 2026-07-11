# データベーススキーマ

本ドキュメントは、Cloud SQL for PostgreSQLに構築するスキーマの詳細をまとめたものです。マイグレーションスクリプトの実体は `migrations/001_init_schema.sql` です。

## 拡張機能

| 拡張機能 | 用途 |
|---|---|
| `postgis` | 地理空間型（`GEOGRAPHY`）とGiSTインデックスによる近隣検索を可能にする |
| `vector`（pgvector） | `VECTOR`型とHNSW/IVFFlatインデックスによる類似度検索を可能にする |
| `google_ml_integration` | SQL関数呼び出し（`google_ml.embedding(...)`相当）により、テキストのembeddingをDB側で生成する。アプリケーション側では外部embeddingモデルを呼び出さない方針のため必須 |

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
```

## テーブル: regional_resources（地域資源）

地域資源のメタデータ・位置情報・embeddingベクトルを1つのテーブルで管理します。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| `resource_id` | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` | 一意識別子 |
| `name` | TEXT | NOT NULL | 地域資源の名称 |
| `category` | TEXT | NOT NULL | カテゴリ |
| `description` | TEXT | NOT NULL | 説明文（embedding生成の元データ） |
| `location` | GEOGRAPHY(POINT, 4326) | NOT NULL | 位置情報 |
| `file_url` | TEXT | NULL可 | 添付ファイルのURL（署名付きURL） |
| `embedding` | VECTOR(768) | NOT NULL | `description`から`google_ml.embedding(...)`で生成 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` | 作成日時 |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` | 更新日時 |

**インデックス**

- `idx_resources_location`: `USING GIST (location)` — `ST_DWithin`による近隣検索を高速化
- `idx_resources_embedding`: `USING hnsw (embedding vector_cosine_ops)` — `<=>`演算子によるコサイン類似度ソートを高速化

**embeddingの生成方法**: INSERT文の中で`google_ml.embedding(description)`相当のSQL関数呼び出しにより、DB側でembeddingが生成・格納されます。アプリケーション側では次元数768のプレースホルダ（空リスト等）を渡すのみです。

## テーブル: consultation_logs（相談履歴）

相談リクエスト（質問文・位置情報）と、参照した地域資源・生成結果を記録します。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| `log_id` | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` | 一意識別子 |
| `query_text` | TEXT | NOT NULL | 質問文 |
| `query_location` | GEOGRAPHY(POINT, 4326) | NOT NULL | 質問時の位置情報 |
| `referenced_resource_ids` | UUID[] | NOT NULL | 参照した地域資源のIDリスト |
| `generated_text` | TEXT | NOT NULL | 生成された回答テキスト |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` | 記録日時 |

> **注記**: `query_text`に個人情報が含まれる可能性があるため、保持期間・アクセス権限をポリシーとして定めることを推奨します（design.md Security Considerations参照）。

## テーブル: vacant_property_candidates（居抜き物件候補）

Places APIで検知した`CLOSED_PERMANENTLY`（完全閉店・廃業）スポットを`place_id`をキーとしたUPSERTで保存/更新します。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| `candidate_id` | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` | 一意識別子 |
| `place_id` | TEXT | UNIQUE NOT NULL | Google Places APIのPlace ID。重複防止・同一性判定のキー |
| `name` | TEXT | NOT NULL | 旧店舗名 |
| `location` | GEOGRAPHY(POINT, 4326) | NOT NULL | 位置情報 |
| `business_status` | TEXT | NOT NULL | `OPERATIONAL` / `CLOSED_TEMPORARILY` / `CLOSED_PERMANENTLY`のいずれか（アプリ側`BusinessStatus` Enumで検証） |
| `types` | TEXT[] | NOT NULL | 業種・ジャンルタグ配列（例: `{restaurant, cafe}`） |
| `address` | TEXT | NULL可 | 住所 |
| `phone_number` | TEXT | NULL可 | 電話番号 |
| `data_fetched_at` | TIMESTAMPTZ | NOT NULL | このレコードのデータをGoogleから取得した時刻 |
| `last_review_time` | TIMESTAMPTZ | NULL可 | 取得できた最新レビューの投稿時刻 |
| `estimated_closure_period_start` | TIMESTAMPTZ | NULL可 | 推定廃業時期レンジの開始 |
| `estimated_closure_period_end` | TIMESTAMPTZ | NULL可 | 推定廃業時期レンジの終了 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` | 作成日時 |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` | 更新日時 |

**インデックス**

- `idx_vacant_properties_location`: `USING GIST (location)` — `ST_DWithin`による地理的絞り込みを高速化
- `idx_vacant_properties_business_status`: `business_status`一致条件による絞り込みを高速化
- `idx_vacant_properties_types`: `USING GIN (types)` — `types`配列の重なり判定（`&&`演算子）を高速化
- `place_id`のUNIQUE制約により、自動的に一意インデックスが作成される

## 主要なクエリパターン

### ハイブリッド検索（regional_resources）

```sql
SELECT *
FROM regional_resources
WHERE ST_DWithin(
        location,
        ST_MakePoint(:longitude, :latitude)::geography,
        :radius_km * 1000
      )
ORDER BY embedding <=> google_ml.embedding(:query_text)
LIMIT :top_k;
```

### 居抜き物件の検索（vacant_property_candidates）

```sql
SELECT *
FROM vacant_property_candidates
WHERE ST_DWithin(
        location,
        ST_MakePoint(:longitude, :latitude)::geography,
        :radius_km * 1000
      )
  AND business_status = :business_status
  AND (:types::text[] IS NULL OR types && :types::text[])
ORDER BY location <-> ST_MakePoint(:longitude, :latitude)::geography
LIMIT :limit;
```

### 居抜き物件のUPSERT

```sql
INSERT INTO vacant_property_candidates (place_id, name, location, business_status, types, ...)
VALUES ($1, $2, ST_MakePoint($3, $4)::geography, $5, $6, ...)
ON CONFLICT (place_id) DO UPDATE SET
    name = EXCLUDED.name,
    location = EXCLUDED.location,
    business_status = EXCLUDED.business_status,
    types = EXCLUDED.types,
    ...
    updated_at = now();
```

すべてのクエリはパラメータ化クエリ（`asyncpg`のプレースホルダ`$1`, `$2`, ...）で構築され、文字列連結によるSQLインジェクションのリスクを排除しています。実装の詳細は`src/regional_revitalization/postgres_repository.py`・`src/regional_revitalization/postgres_vacant_property_repository.py`を参照してください。

## マイグレーションの実行方法

```bash
psql "$DATABASE_URL" -f migrations/001_init_schema.sql
psql "$DATABASE_URL" -f migrations/002_admin_schema.sql
psql "$DATABASE_URL" -f migrations/003_search_and_property_details.sql
```

Cloud SQLへの接続には、プライベートIPまたはCloud SQL Auth Proxy経由での接続を推奨します（パブリックIPは無効化）。

## 管理画面用スキーマ（002_admin_schema.sql）

管理画面（`frontend/admin/`、APIRunの`/admin/*`エンドポイント）向けに以下を追加します。

| テーブル | 用途 |
|---|---|
| `admin_users` | 管理ユーザー（ログインID・パスワードハッシュ・表示名・`role`列（現状`full_admin`固定）） |
| `admin_sessions` | ログインセッション（ランダムトークンをそのままセッションIDとして使用） |
| `resource_update_requests` | 利用者からの地域資源データ更新依頼（`status`: pending/approved/rejected） |

また、`regional_resources`・`vacant_property_candidates`に市町村別統計用の`municipality`列（デフォルト空文字列）を追加します。

## 検索履歴・Places APIリアルタイム検索用スキーマ（003_search_and_property_details.sql）

| 追加内容 | 用途 |
|---|---|
| `vacant_property_candidates.rent_yen`/`area_sqm`/`built_year`/`structure` | 賃料・面積・築年数・構造。Google Places APIからは取得できないため、管理画面での手動編集専用（フロントには表示しない） |
| `search_requests`テーブル | 利用者の居抜き物件検索リクエスト（`POST /vacant-properties/search`）を常に記録。場所・条件・結果件数を保存する |
| `places_search_results`テーブル | 管理画面で「この場所でGoogle Places APIを検索する」を実行した結果を登録待ちの状態で一時保存。管理者が個別に確認して登録するまでは`vacant_property_candidates`には反映されない |

## 接続方式

アプリ本体サービス（APIRun）・居抜き物件同期サービスは`asyncpg`を用いてCloud SQLへ接続します。接続文字列やコネクションプールはコンストラクタで受け取る設計になっており、実際の接続確立は呼び出し側（アプリ起動処理等）の責務です。

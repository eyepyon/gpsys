# APIリファレンス

本ドキュメントは、アプリ本体サービス（APIRun）と推論サービス（InferRun）が提供するHTTP APIエンドポイントの仕様をまとめたものです。実装は`src/regional_revitalization/api.py`（APIRun）、`src/regional_revitalization/infer_run_api.py`（InferRun）を参照してください。

## アプリ本体サービス（APIRun）

FastAPIアプリケーション（`app = FastAPI(...)`、`src/regional_revitalization/api.py`）。既定では依存性注入によりインメモリ実装が使われますが、実運用時は`set_resource_repository()`等の関数、または`app.dependency_overrides`でCloud SQL/Cloud Storage/推論サービスクライアントの実装に差し替えます。

### POST /consultations — 相談応答

利用者からの質問文と位置情報を受け付け、ハイブリッド検索結果をコンテキストとして推論サービスに回答生成を依頼します。

**リクエストボディ**

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `query_text` | string | ○ | - | 利用者からの質問文（空文字列不可） |
| `latitude` | float | ○ | - | 利用者の位置情報（緯度、-90〜90） |
| `longitude` | float | ○ | - | 利用者の位置情報（経度、-180〜180） |
| `radius_km` | float | ○ | - | 検索半径（キロメートル、正の数） |
| `top_k` | int | - | 5 | 生成時に利用する上位件数 |

**レスポンスボディ（200）**

```json
{
  "generated_text": "生成された回答テキスト",
  "referenced_resources": [
    {
      "resource_id": "uuid文字列",
      "name": "地域資源名",
      "category": "カテゴリ",
      "description": "説明文",
      "latitude": 35.4,
      "longitude": 138.9,
      "file_url": "https://.../signed-url または null"
    }
  ]
}
```

**エラーレスポンス**

| ステータス | 条件 |
|---|---|
| 400 | `query_text`が空文字列、`radius_km<=0`、緯度経度が範囲外等の入力検証エラー |
| 422 | リクエストボディの型・必須項目が不正（FastAPI/Pydanticの標準検証） |
| 502 | 推論サービス（InferRun）呼び出しの失敗・タイムアウト |

### POST /resources — 地域資源の登録

自治体職員等が地域資源（施設・イベント・支援制度等）を登録します。添付ファイルはbase64エンコードして送信します。

**リクエストボディ**

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `name` | string | ○ | - | 地域資源の名称（空文字列不可） |
| `category` | string | ○ | - | カテゴリ（空文字列不可） |
| `description` | string | ○ | - | 説明文（空文字列不可、embedding生成の元データ） |
| `latitude` | float | ○ | - | 位置情報（緯度） |
| `longitude` | float | ○ | - | 位置情報（経度） |
| `file_base64` | string \| null | - | null | 添付ファイルのbase64エンコード文字列 |
| `content_type` | string \| null | - | null | 添付ファイルのMIMEタイプ（`file_base64`指定時は必須） |

**レスポンスボディ（201）**

```json
{
  "resource_id": "uuid文字列",
  "name": "地域資源名",
  "category": "カテゴリ",
  "description": "説明文",
  "latitude": 35.4,
  "longitude": 138.9,
  "file_url": "https://.../signed-url または null"
}
```

**エラーレスポンス**

| ステータス | 条件 |
|---|---|
| 400 | `name`/`category`/`description`の空文字列、緯度経度が範囲外、`file_base64`指定時の`content_type`未指定、base64デコード失敗等 |
| 422 | リクエストボディの型・必須項目が不正 |
| 503 | Cloud Storageへのファイルアップロード失敗（データベースへの登録は実行されない） |

### POST /vacant-properties/search — 居抜き物件の検索

位置・営業状態・業種タグで居抜き物件候補を検索します。

**リクエストボディ**

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `latitude` | float | ○ | - | 検索基準位置の緯度 |
| `longitude` | float | ○ | - | 検索基準位置の経度 |
| `radius_km` | float | ○ | - | 検索半径（キロメートル、正の数） |
| `business_status` | string | ○ | - | `OPERATIONAL` / `CLOSED_TEMPORARILY` / `CLOSED_PERMANENTLY`のいずれか |
| `types` | string[] \| null | - | null | 業種・ジャンルタグによる絞り込み条件（指定時は候補のtypesと積集合が空でないもののみ返す） |
| `limit` | int | - | 10 | 取得件数の上限 |

**レスポンスボディ（200）**

```json
{
  "candidates": [
    {
      "place_id": "ChIJ...",
      "name": "旧店舗名",
      "latitude": 35.4,
      "longitude": 138.9,
      "business_status": "CLOSED_PERMANENTLY",
      "types": ["restaurant", "cafe"],
      "address": "住所または null",
      "phone_number": "電話番号または null",
      "estimated_closure_period_start": "2024-01-01T00:00:00 または null",
      "estimated_closure_period_end": "2024-01-10T00:00:00 または null"
    }
  ]
}
```

**エラーレスポンス**

| ステータス | 条件 |
|---|---|
| 400 | `radius_km<=0`、`limit<1`、緯度経度が範囲外 |
| 422 | `business_status`がEnumに存在しない値等、リクエストボディの型が不正 |
| 500 | データベースエラー等の予期しない例外 |

## 推論サービス（InferRun）

FastAPIアプリケーション（`src/regional_revitalization/infer_run_api.py`）。APIRunからのみ呼び出される想定で、本番環境ではCloud RunのIAM認証（`allUsers`非公開）で保護されます。

### POST /generate — テキスト生成

プロンプトとコンテキストスニペットを受け取り、Gemma 4 12B QATモデルによる生成結果を返します（現状の実装は`MockInferenceClient`によるモック生成。実際のGemma呼び出しへの差し替えは`set_inference_client()`で行います）。

**認証**

`Authorization: Bearer <token>`ヘッダーが必要です（ローカル実行・テスト用のモック認証。本番はCloud Run IAM認証に置き換えます）。

- 環境変数`REQUIRE_AUTH=false`の場合、認証チェックをスキップします（ローカル開発向け）。
- 期待するトークン文字列は環境変数`INFER_RUN_EXPECTED_TOKEN`（未設定時は`mock-service-token`）と比較します。

**リクエストボディ**

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `prompt` | string | ○ | - | 生成の元になるプロンプト文字列 |
| `context_snippets` | string[] | - | `[]` | ハイブリッド検索結果を文字列化したコンテキスト一覧 |
| `max_tokens` | int | - | 512 | 生成する最大トークン数 |
| `temperature` | float | - | 0.2 | 生成時のサンプリング温度 |

**レスポンスボディ（200）**

```json
{
  "generated_text": "生成されたテキスト",
  "input_tokens": 42,
  "output_tokens": 18
}
```

`input_tokens`/`output_tokens`は常に0以上の整数です（空のプロンプト・コンテキストの場合も0を許容）。

**エラーレスポンス**

| ステータス | 条件 |
|---|---|
| 403 | 認証ヘッダーが無い、形式が不正、またはトークンが一致しない |
| 422 | リクエストボディの型が不正 |

## 共有インスタンスの差し替え（テスト・実運用向け）

APIRun・InferRunはいずれも、依存するリポジトリ・クライアントをモジュールレベルの共有インスタンスとして保持し、`set_*`関数で差し替えられる設計になっています。

| モジュール | 差し替え関数 | 用途 |
|---|---|---|
| `api.py` | `set_resource_repository()` | `InMemoryResourceRepository` → `PostgresResourceRepository`（Cloud SQL接続） |
| `api.py` | `set_storage_client()` | `InMemoryStorageClient` → `GcsStorageClient`（Cloud Storage接続） |
| `api.py` | `set_inference_client()` | `MockInferenceClient` → 実際の推論クライアント |
| `api.py` | `set_vacant_property_repository()` | `InMemoryVacantPropertyRepository` → `PostgresVacantPropertyRepository` |
| `infer_run_api.py` | `set_inference_client()` | `MockInferenceClient` → Gemma 4 12B QATモデル呼び出し実装 |

# 開発ガイド

## 前提条件

- Python 3.11以上

## セットアップ

```bash
pip install -e ".[dev]"
```

追加の依存関係グループ（`pyproject.toml`の`[project.optional-dependencies]`）:

| グループ | 用途 | 主なパッケージ |
|---|---|---|
| `dev` | テスト実行 | `pytest`, `hypothesis`, `httpx` |
| `api` | FastAPI APIエンドポイントの実行 | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `google-auth` |
| `postgres` | Cloud SQL for PostgreSQL実装の実行 | `asyncpg` |
| `gcs` | Cloud Storage実装の実行 | `google-cloud-storage` |

必要なものを組み合わせてインストールしてください。

```bash
pip install -e ".[dev,api,postgres,gcs]"
```

## プロジェクト構成

```
regional-revitalization-support-system/
├── src/regional_revitalization/   # アプリケーションコード
├── tests/                          # 単体テスト・Property-Based Test・E2Eテスト
├── migrations/                     # Cloud SQL用マイグレーションスクリプト（DDL）
├── terraform/                      # GCPリソースのTerraformコード
├── docker/                         # 各サービスのDockerfile（api/infer/vacant_sync）
├── frontend/                       # 動作確認用の静的HTMLページ（本格的な業務用UIではない）
├── .github/workflows/              # GitHub ActionsのCI/CDワークフロー（ci.yml, deploy.yml）
├── docs/                           # 本ドキュメント群
└── .kiro/specs/.../                # 要件定義書・設計書・実装タスクリスト
```

各モジュールの役割は[architecture.md](./architecture.md)の「ソースコード構成」を参照してください。`frontend/`の使い方は[frontend/README.md](../frontend/README.md)を参照してください。

## テストの実行方法

すべてのテスト（単体テスト、Property-Based Test、結合テスト、エンコーディング統一確認テストを含む）は`pytest`で実行します。

```bash
pytest
```

特定のテストファイルのみを実行する場合はパスを指定します。

```bash
pytest tests/test_e2e.py
```

### テストの種類

| テストファイル（例） | 種類 | 内容 |
|---|---|---|
| `tests/test_models.py` | 単体テスト + PBT | `GeoPoint`等のデータモデルの検証ロジック |
| `tests/test_repository.py` | 単体テスト + PBT | 地理空間検索・ベクトル検索・ハイブリッド検索 |
| `tests/test_registration.py` | 単体テスト + PBT | 地域資源登録（round-trip、file_url整合性） |
| `tests/test_consultation.py` | 単体テスト + PBT | 相談応答（正常系・エラー伝播） |
| `tests/test_vacant_property.py` | 単体テスト + PBT | 居抜き物件のデータモデル・検索・同期処理 |
| `tests/test_api.py` | 単体テスト | APIRunのHTTPエンドポイント |
| `tests/test_infer_run_api.py` | 単体テスト | InferRunのHTTPエンドポイント（認証含む） |
| `tests/test_e2e.py` | 結合テスト | フロー1〜4のエンドツーエンドの流れ |
| `tests/test_postgres_repository.py` | 静的検証 + 統合テスト（スキップ付き） | SQLクエリのパラメータ化確認、実DB接続テスト |
| `tests/test_postgres_vacant_property_repository.py` | 静的検証 + 統合テスト（スキップ付き） | 同上（居抜き物件） |
| `tests/test_encoding_compliance.py` | 静的検証 | UTF-8・LF改行の統一確認 |

### 実DBが必要な統合テストについて

`tests/test_postgres_repository.py`・`tests/test_postgres_vacant_property_repository.py`に含まれる一部のテストは、PostGIS/pgvector/`google_ml_integration`拡張を有効化したPostgreSQLコンテナが必要なため、該当環境が無い場合は自動的にスキップされます（`@pytest.mark.skip`）。

実行する場合は以下の手順です。

1. PostGIS/pgvector/`google_ml_integration`拡張を有効化したPostgreSQL環境を用意する（Cloud SQLまたはDockerコンテナ）。
2. `migrations/001_init_schema.sql`を適用する。
3. 環境変数`TEST_DATABASE_URL`に接続文字列を設定する。
4. 各テストファイル内の`@pytest.mark.skip(...)`を解除する。
5. `pytest`を実行する。

## Property-Based Testing（PBT）について

本プロジェクトは、正当性プロパティ（`design.md`の「Correctness Properties」章）をHypothesisによるProperty-Based Testingで検証しています。例:

- 地理空間検索の距離制約・順序性・件数制約
- ベクトル検索の類似度順序性・件数制約
- ハイブリッド検索の一意性・地理的整合性
- 登録の往復性（round-trip）、ファイル有無とURLの整合性
- 居抜き物件のplace_id一意性、業種フィルタの正確性、廃業時期推定レンジの整合性

各プロパティの詳細は`.kiro/specs/regional-revitalization-support-system/design.md`の「Correctness Properties」章、対応するテストコードのdocstringを参照してください。

## コーディング規約

- すべてのソースコード・ドキュメントのコメント/docstringは**日本語**で記述します。
- ファイルの文字コードは**UTF-8**、改行コードは**LF**で統一します。
- `tests/test_encoding_compliance.py`が`src/`・`tests/`配下の全`.py`ファイルについてUTF-8デコード可能性とCRLF/CR不在を自動確認します。

### 実DB/実外部APIが未接続でも動作する設計パターン

Cloud SQL・Cloud Storage・Places API等、外部リソースに依存する実装は以下のパターンに従っています。

1. Protocolでインターフェースを定義する（例: `ResourceRepository`, `StorageClient`, `PlacesApiClient`）。
2. テスト用インメモリ/モック実装を用意する（例: `InMemoryResourceRepository`, `InMemoryStorageClient`, `MockPlacesApiClient`）。
3. 実運用向け実装（`asyncpg`, `google-cloud-storage`, `httpx`等を使用）は、`try/except ImportError`でパッケージ未インストール時のimportエラーを防ぎ、型ヒントのみ`TYPE_CHECKING`ガードで参照する。

これにより、外部パッケージがインストールされていない開発環境でも、コードの読み込み・インメモリ実装によるテストが常に可能です。

## コンテナイメージのローカルビルド

各サービスのDockerfileは`docker/`ディレクトリに配置されています（`docker/api/`, `docker/infer/`, `docker/vacant_sync/`, `docker/frontend/`）。ローカルでビルドを確認する場合はリポジトリルートで以下を実行します（Docker CLIが必要です）。

```bash
docker build -f docker/api/Dockerfile -t regional-revitalization-api:local .
docker build -f docker/frontend/Dockerfile -t inuki-frontend:local .
```

GCPへのイメージのプッシュ、Terraformとの連携、GitHub ActionsによるCI/CDの詳細は[deployment-guide.md](./deployment-guide.md)を参照してください。

## 静的解析・型チェック

現時点で`mypy`等の型チェッカーはプロジェクトに導入されていません。導入する場合は`pyproject.toml`に依存関係を追加し、CIパイプラインに組み込むことを推奨します。

## Gitに関する注意事項

`.gitignore`により、以下はリポジトリに含まれません。

- `terraform.tfvars`（機密情報を含む可能性があるため）
- `.terraform/`、`*.tfstate`等のTerraform実行時生成物
- `__pycache__/`、`.pytest_cache/`、`.hypothesis/`等のキャッシュ

`terraform.tfvars`を作成する場合は`terraform/terraform.tfvars.example`を参考にし、機密値（`db_password`, `places_api_key`）は環境変数（`TF_VAR_db_password`等）やCI/CDのシークレットストアから注入してください。

# 地方創生支援システム (regional-revitalization-support-system)

位置情報データベース（地理空間インデックス）とベクトルデータベース（pgvector）を活用し、
地方創生に関する相談対応・地域資源の検索・登録を行うシステムです。
さらに、Google Maps Platform Places APIを用いて閉店・廃業したスポットを検知し
「居抜き物件」として蓄積・検索できる機能を提供します。

詳細な要件・設計は以下を参照してください。

- 要件定義書: `.kiro/specs/regional-revitalization-support-system/requirements.md`
- 設計書: `.kiro/specs/regional-revitalization-support-system/design.md`
- タスクリスト: `.kiro/specs/regional-revitalization-support-system/tasks.md`

## 構成

- `src/regional_revitalization/`: アプリ本体サービス（APIRun）・推論サービス（InferRun）・
  居抜き物件同期サービスのPythonソースコード
- `tests/`: 単体テスト・Property-Based Test（Hypothesis）・結合テスト（E2Eテスト）
- `migrations/`: Cloud SQL for PostgreSQL用のマイグレーションスクリプト（DDL）
- `terraform/`: GCPリソース（Cloud Run、Cloud SQL、Cloud Storage等）のTerraformコード

## セットアップ

Python 3.11以上が必要です。

```bash
pip install -e ".[dev]"
```

FastAPIのAPIエンドポイントを含めて動作させる場合は、`api`エクストラも追加でインストールします。

```bash
pip install -e ".[dev,api]"
```

Cloud SQL for PostgreSQL用の実装（`asyncpg`）やCloud Storage用の実装
（`google-cloud-storage`）を利用する場合は、それぞれ`postgres`・`gcs`エクストラを
インストールしてください。

```bash
pip install -e ".[dev,postgres,gcs]"
```

## テストの実行方法

すべてのテスト（単体テスト、Property-Based Test、結合テスト、
エンコーディング統一確認テストを含む）は`pytest`で実行します。

```bash
pytest
```

特定のテストファイルのみを実行する場合は、パスを指定します。

```bash
pytest tests/test_e2e.py
```

なお、`tests/test_postgres_repository.py`・`tests/test_postgres_vacant_property_repository.py`
に含まれる一部の統合テストは、PostGIS/pgvector/`google_ml_integration`拡張を
有効化したPostgreSQLコンテナが必要なため、該当環境が無い場合は自動的に
スキップされます。

## コード規約

すべてのソースコード・ドキュメントは日本語コメント・UTF-8・LF改行で統一します
（`tests/test_encoding_compliance.py`で自動確認しています）。

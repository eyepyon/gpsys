# ドキュメント一覧

本ディレクトリ（`docs/`）には、地方創生支援システム（regional-revitalization-support-system）に関する人間向けの詳細ドキュメントを配置しています。

仕様策定プロセスで作成した要件定義書・設計書・タスクリストは `.kiro/specs/regional-revitalization-support-system/` にありますが、こちらは開発者・運用者が実際にシステムを理解し、開発・デプロイ・運用するための実務的なドキュメントです。

## 目次

| ドキュメント | 内容 |
|---|---|
| [architecture.md](./architecture.md) | システム全体のアーキテクチャ、コンポーネント構成、データフロー |
| [api-reference.md](./api-reference.md) | アプリ本体サービス（APIRun）・推論サービス（InferRun）のAPIエンドポイント仕様 |
| [database-schema.md](./database-schema.md) | Cloud SQL for PostgreSQLのテーブル・インデックス・拡張機能の詳細 |
| [vacant-property-feature.md](./vacant-property-feature.md) | 居抜き物件発見機能（Places API連携）の詳細解説 |
| [development-guide.md](./development-guide.md) | ローカル開発環境のセットアップ、テストの実行方法、コーディング規約 |
| [deployment-guide.md](./deployment-guide.md) | Terraformによるインフラ構築・GCPへのデプロイ手順 |

## 関連ドキュメント（仕様策定プロセス由来）

以下は本システムの要件・設計・実装計画を記録した仕様ドキュメントです。仕様の背景や正当性プロパティ（Property-Based Testingの検証対象）を確認したい場合はこちらを参照してください。

- 要件定義書: `.kiro/specs/regional-revitalization-support-system/requirements.md`
- 設計書: `.kiro/specs/regional-revitalization-support-system/design.md`
- 実装タスクリスト: `.kiro/specs/regional-revitalization-support-system/tasks.md`

## システム概要

本システムは、以下の2つの中核価値を提供します。

1. **地方創生RAG相談システム**: 位置情報データベース（PostGIS）とベクトルデータベース（pgvector）を組み合わせたハイブリッド検索により、利用者の質問と現在地に応じて関連性の高い地域資源（施設・イベント・支援制度等）を検索し、Gemma 4 12B QATモデルによる回答生成（RAG）を行う。
2. **居抜き物件発見システム**: Google Maps Platform Places APIを活用し、閉店・廃業したスポット（`business_status == CLOSED_PERMANENTLY`）を定期的に検知・蓄積し、不動産屋も把握していない「居抜き物件」情報を出店検討者に提供する。

すべてGoogle Cloud Platform（us-central1リージョン）上に構築され、インフラはTerraformでコード化されています。

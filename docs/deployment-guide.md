# デプロイガイド（Terraform / GCP）

本ドキュメントは、Terraformを用いてGCPインフラを構築し、本システムをデプロイする手順をまとめたものです。Terraformコードの実体は`terraform/`ディレクトリです。

> **重要な注記**: `terraform/`配下のコードは、Terraform CLIが利用できない開発環境で作成されました。`terraform init`/`validate`/`plan`/`apply`による実行検証は未実施です。コードレビューレベルでの構文・構造の妥当性確認のみ済んでいます。適用前に必ず`terraform validate`・`terraform plan`で内容を確認してください。

## 前提条件

- 課金設定が有効化されたGCPプロジェクトが既に存在すること
- Terraform CLI（推奨バージョンは`terraform/versions.tf`を参照）
- `gcloud` CLIによる認証、または対象GCPプロジェクトへの十分な権限を持つサービスアカウント
- 以下のAPIが有効化可能であること（`main.tf`内で`google_project_service`により有効化を試みるが、組織ポリシーにより制限される場合は事前に有効化しておくこと）
  - `run.googleapis.com`
  - `sqladmin.googleapis.com`
  - `servicenetworking.googleapis.com`
  - `vpcaccess.googleapis.com`
  - `secretmanager.googleapis.com`
  - `storage.googleapis.com`
  - `cloudscheduler.googleapis.com`
  - `aiplatform.googleapis.com`
  - `iam.googleapis.com`

## ディレクトリ構成

```
terraform/
├── versions.tf                 # Terraform/プロバイダのバージョン制約
├── variables.tf                 # ルート構成の入力変数
├── main.tf                      # 各モジュールの呼び出し、API有効化
├── outputs.tf                   # ルート構成の出力値
├── terraform.tfvars.example      # 変数のサンプル（実際の値・機密情報は含まない）
└── modules/
    ├── network/                              # VPCコネクタ + Private Services Access
    ├── cloudsql/                              # Cloud SQL for PostgreSQL + Secret Manager(DB接続情報)
    ├── storage/                               # 非公開Cloud Storageバケット
    ├── cloudrun_app/                          # アプリ本体サービス(APIRun)
    ├── cloudrun_inference/                    # 推論サービス(InferRun, GPU L4)
    ├── cloudrun_jobs_vacant_property_sync/    # 居抜き物件同期サービス(Cloud Run Jobs)
    └── scheduler/                             # Cloud Scheduler(定期トリガー)
```

## 必要な変数一覧

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `project_id` | ○ | - | GCPプロジェクトID |
| `region` | - | `us-central1` | 全リソースの作成リージョン（変更しないこと。推論サービスのGPU L4可用性の制約による） |
| `environment` | - | `dev` | 環境識別子（リソース名サフィックス） |
| `app_service_name` | - | `regional-revitalization-api` | APIRunのCloud Runサービス名 |
| `app_image` | ○ | - | APIRunのコンテナイメージURL |
| `inference_service_name` | - | `regional-revitalization-infer` | InferRunのCloud Runサービス名 |
| `inference_image` | ○ | - | InferRunのコンテナイメージURL |
| `vacant_sync_job_name` | - | `vacant-property-sync` | 居抜き物件同期サービスのCloud Run Jobs名 |
| `vacant_sync_image` | ○ | - | 居抜き物件同期サービスのコンテナイメージURL |
| `vpc_network_name` | - | `default` | VPCコネクタを紐づける対象VPCネットワーク名 |
| `vpc_connector_cidr` | - | `10.8.0.0/28` | VPCアクセスコネクタのCIDR範囲(/28) |
| `db_instance_name` | - | `regional-revitalization-db` | Cloud SQLインスタンス名 |
| `db_tier` | - | `db-custom-2-8192` | Cloud SQLのマシンタイプ |
| `db_name` | - | `regional_revitalization` | アプリケーション用DB名 |
| `db_user` | - | `app_user` | アプリケーション用DBユーザー名 |
| `db_password` | ○（機密） | - | アプリケーション用DBユーザーのパスワード |
| `storage_bucket_name` | ○ | - | 地域資源ファイル保存用バケット名（グローバル一意） |
| `places_api_key` | ○（機密） | - | Google Maps Platform Places APIキー |
| `vacant_sync_schedule` | - | `0 3 * * *` | 同期サービスの実行スケジュール(unix-cron) |
| `vacant_sync_time_zone` | - | `Etc/UTC` | スケジュールのタイムゾーン |
| `labels` | - | `{app = "regional-revitalization"}` | 全リソース共通ラベル |

## デプロイ手順

### 1. コンテナイメージのビルド・プッシュ

APIRun・InferRun・居抜き物件同期サービスの3つのコンテナイメージをビルドし、Artifact Registry等にプッシュします（Dockerfileは現時点で未整備のため、各サービスのエントリポイント（`api.py`, `infer_run_api.py`, `vacant_property_sync_job.py`）を起動するコンテナイメージを別途用意してください）。

- APIRun: `uvicorn regional_revitalization.api:app`を起動するイメージ
- InferRun: `uvicorn regional_revitalization.infer_run_api:app`を起動するイメージ（Gemma 4 12B QATモデルの重み・推論ライブラリを含む）
- 居抜き物件同期サービス: `python -m regional_revitalization.vacant_property_sync_job`を実行するイメージ

### 2. 変数の設定

`terraform/terraform.tfvars.example`を参考に、機密情報以外の変数を設定します。**機密情報（`db_password`, `places_api_key`）は`terraform.tfvars`に平文で記載しないでください。**

```bash
export TF_VAR_db_password="..."
export TF_VAR_places_api_key="..."
```

### 3. Terraformの初期化・検証・適用

```bash
cd terraform
terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

### 4. マイグレーションの適用

Cloud SQLインスタンス作成後、`migrations/001_init_schema.sql`を適用します。

```bash
psql "$DATABASE_URL" -f ../migrations/001_init_schema.sql
```

### 5. 動作確認

- APIRunのヘルスチェック（例: `GET /docs`でFastAPIのSwagger UIが表示されることを確認）
- `POST /consultations`・`POST /resources`・`POST /vacant-properties/search`の簡易リクエスト
- Cloud Schedulerが居抜き物件同期サービス（Cloud Run Jobs）を定期実行することの確認

## 機密情報の取り扱い方針

- `db_password`・`places_api_key`は`sensitive = true`が付与されているため、CLIの標準出力・`plan`差分表示には平文が表示されません。ただし、実際の値はこれらの変数からSecret Managerシークレットの初期バージョンとして書き込まれます。
- 最終的にDB接続情報・Places APIキーはSecret Manager（`google_secret_manager_secret_version`）に格納されます。各サービスはSecret Manager経由（Cloud Runの`secret_key_ref`）で環境変数として受け取り、コンテナイメージや設定ファイルに平文を書き込みません。
- Places APIキーへのSecret Managerアクセス権限（`roles/secretmanager.secretAccessor`）は、居抜き物件同期サービスの実行用サービスアカウントにのみ付与されます。APIRun・InferRunのサービスアカウントには付与されません。
- **tfstateに関する制約**: `sensitive = true`はCLI出力の抑制のみであり、値自体はtfstateファイルの属性値として保存されます（Terraformの一般的な制約）。運用時は以下を推奨します。
  - tfstateはリモートバックエンド（暗号化・アクセス制御されたGCSバケット等）に保存する
  - tfstateファイルへのアクセス権限を最小化する
  - 機密値のローテーションはSecret Manager側（`gcloud secrets versions add`等）で行い、Terraformの再適用による意図しない値の上書きを避ける

## モジュール概要

| モジュール | 内容 |
|---|---|
| `modules/network` | Serverless VPC Access コネクタ、Cloud SQLのプライベートIP接続に必要なPrivate Services Access（VPCピアリング） |
| `modules/cloudsql` | Cloud SQL for PostgreSQLインスタンス（プライベートIPのみ、`google_ml_integration`拡張有効化フラグ）、DB/ユーザー作成、DB接続情報のSecret Manager登録 |
| `modules/storage` | 非公開Cloud Storageバケット（`uniform_bucket_level_access`, `public_access_prevention = "enforced"`） |
| `modules/cloudrun_app` | APIRun（アプリ本体サービス）のCloud Runサービス |
| `modules/cloudrun_inference` | InferRun（推論サービス、GPU L4、内部限定公開）のCloud Runサービス |
| `modules/cloudrun_jobs_vacant_property_sync` | 居抜き物件同期サービスのCloud Run Jobs、Places APIキーのSecret Manager登録・アクセス制御 |
| `modules/scheduler` | Cloud Schedulerによる定期トリガー（居抜き物件同期サービス起動） |

## リージョンについて

すべてのリソースは`region`変数（デフォルト: `us-central1`）に従って作成されます。design.mdの方針（GPU L4はus-central1でホスト）に合わせてデフォルト値を`us-central1`としています。他リージョンへの変更は、推論サービスのGPU可用性の制約により推奨しません。

## デプロイ後の運用チェックリスト

- [ ] `terraform validate`・`terraform plan`で構文・変更内容を確認した
- [ ] Cloud SQLインスタンスにマイグレーション（`migrations/001_init_schema.sql`）を適用した
- [ ] Secret ManagerにDB接続情報・Places APIキーが正しく登録されていることを確認した
- [ ] InferRunが`allUsers`に公開されておらず、APIRunのサービスアカウントのみが呼び出せることを確認した
- [ ] Cloud Storageバケットが非公開設定（`public_access_prevention = "enforced"`）になっていることを確認した
- [ ] Cloud Schedulerのスケジュール（`vacant_sync_schedule`）が、監視対象place_id数とAPIレート制限を踏まえて30日以内に全件リフレッシュされる頻度になっていることを確認した
- [ ] tfstateの保存先（リモートバックエンド）とアクセス権限を確認した

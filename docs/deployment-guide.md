# デプロイガイド（Terraform / GCP / GitHub Actions）

本ドキュメントは、Terraformを用いてGCPインフラを構築し、GitHub ActionsによるCI/CDパイプラインで本システムをデプロイする手順をまとめたものです。Terraformコードの実体は`terraform/`ディレクトリ、GitHub Actionsワークフローは`.github/workflows/`ディレクトリ、Dockerfileは`docker/`ディレクトリです。

> **重要な注記**: `terraform/`配下のコードおよび`docker/`配下のDockerfileは、Terraform CLI・Docker CLIが利用できない開発環境で作成されました。`terraform init`/`validate`/`plan`/`apply`、および`docker build`による実行検証は未実施です。コードレビューレベルでの構文・構造の妥当性確認のみ済んでいます。適用前に必ず`terraform validate`・`terraform plan`、および`docker build`のローカル実行で内容を確認してください。GitHub Actions上のCIジョブ（`ci.yml`）でも自動検証されます。

## デプロイ方式の全体像

本システムは2段階のデプロイ方式を取ります。

1. **初回セットアップ（人間の管理者が実行）**: GCPプロジェクトの初期構築、Terraformのtfstateと地域資源ファイルを共用するGCSバケットの作成、GitHub ActionsからのWorkload Identity Federation（WIF）設定。これらは「GitHub Actionsがまだ認証情報を持っていない」段階のため、人間が十分な権限を持つ認証情報でローカルから実行する必要があります。
2. **継続的デプロイ（GitHub Actionsが実行）**: 初回セットアップ完了後は、`main`ブランチへのpush（マージ）をトリガーに、GitHub Actionsが自動でコンテナイメージのビルド・プッシュとTerraform適用を行います。

### バケット構成に関する注記

**tfstate保存用バケットと、地域資源ファイル保存用バケットは1つのGCSバケットに統合し、プレフィックス（フォルダ相当）で用途を分離します。**

| プレフィックス | 用途 | 管理方法 |
|---|---|---|
| `terraform/state/` | Terraformのtfstate | `versions.tf`の`backend "gcs" { prefix = "terraform/state" }` |
| `resources/` | 地域資源ファイル（画像・PDF等） | APIRunが`registration.py`経由でアップロード |

バケットが1つに統合される分、IAM条件（Condition）により、APIRun実行用サービスアカウントには`resources/`プレフィックス配下のオブジェクトのみへのアクセス権限を付与し、tfstate（機密値の断片を含む）へはアクセスできないようにしています（`terraform/modules/storage/main.tf`の`google_storage_bucket_iam_member`参照）。バケット自体は循環依存を避けるためTerraform管理外で事前作成します（下記手順1）。

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
  - `iamcredentials.googleapis.com`（Workload Identity Federation経由のなりすまし（impersonation）に必須）

## ディレクトリ構成

```
terraform/
├── versions.tf                 # Terraform/プロバイダのバージョン制約、GCSリモートバックエンド設定
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
    ├── scheduler/                             # Cloud Scheduler(定期トリガー)
    ├── artifact_registry/                     # コンテナイメージ格納用リポジトリ
    └── github_actions_wif/                    # GitHub ActionsからのWorkload Identity連携

docker/
├── api/Dockerfile             # APIRun用コンテナイメージ
├── infer/Dockerfile           # InferRun用コンテナイメージ
└── vacant_sync/Dockerfile     # 居抜き物件同期サービス用コンテナイメージ

.github/workflows/
├── ci.yml                     # プルリクエスト・push時のテスト・構文検証（再利用可能ワークフロー）
└── deploy.yml                 # mainブランチへのpush時のビルド・デプロイ
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
| `artifact_registry_repository_id` | - | `regional-revitalization` | コンテナイメージを格納するArtifact Registryリポジトリ名 |
| `enable_github_actions_wif` | - | `false` | GitHub Actions用のWorkload Identity連携（プール・プロバイダ・デプロイ用サービスアカウント）を作成するかどうか（2段階適用の切り替えフラグ） |
| `github_repository` | - | `""` | GitHub ActionsからのWIF認証を許可するGitHubリポジトリ（`"org-name/repo-name"`形式） |

## 初回セットアップ手順（人間の管理者がローカルから実行）

GitHub Actionsはまだ認証情報を持っていないため、以下は`gcloud auth login`等で認証済みの、GCPプロジェクトへの十分な権限（プロジェクト編集者以上を推奨）を持つ人間の管理者がローカル環境から実行します。

### 1. tfstate/地域資源ファイル共用GCSバケットの作成

Terraformの状態ファイル（tfstate）と、地域資源ファイル（画像・PDF等）を1つのバケットに統合し、プレフィックス（`terraform/state/`と`resources/`）で用途を分離します。このバケットを、Terraform管理外で先に作成します（バケット自体をTerraformで管理すると、tfstateの保存先が無い状態でinitする循環依存になるため）。

```bash
gcloud storage buckets create gs://<your-project-id>-regional-revitalization \
  --project=<your-project-id> \
  --location=us-central1 \
  --uniform-bucket-level-access \
  --public-access-prevention=enforced

# バージョニングを有効化し、誤ってstateやファイルを上書きした場合に復元できるようにする
gcloud storage buckets update gs://<your-project-id>-regional-revitalization --versioning
```

このバケット名を、以降の手順（`terraform init -backend-config="bucket=..."`と`storage_bucket_name`変数）の両方に指定します。

### 2. コンテナイメージのビルド・プッシュ（初回のみ手動）

Terraformの初回適用時にはコンテナイメージが必要なため、`main.tf`が参照するArtifact Registryリポジトリを先に作成し、初回イメージを手動でプッシュします。段取りは以下の通りです。

```bash
# Artifact Registryリポジトリのみを先に作成する（--target で対象を絞る）
# <bucket-name>は手順1で作成した共用バケット名（tfstate/地域資源ファイル両用）
cd terraform
terraform init -backend-config="bucket=<bucket-name>"
terraform apply -target=module.artifact_registry -var="project_id=<your-project-id>" \
  -var="app_image=placeholder" -var="inference_image=placeholder" \
  -var="vacant_sync_image=placeholder" -var="storage_bucket_name=<bucket-name>" \
  -var="db_password=$TF_VAR_db_password" -var="places_api_key=$TF_VAR_places_api_key"

# 認証設定
gcloud auth configure-docker us-central1-docker.pkg.dev

# 各イメージをビルド・プッシュする（リポジトリルートで実行）
cd ..
docker build -f docker/api/Dockerfile -t us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/api:latest .
docker push us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/api:latest

docker build -f docker/infer/Dockerfile -t us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/infer:latest .
docker push us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/infer:latest

docker build -f docker/vacant_sync/Dockerfile -t us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/vacant-sync:latest .
docker push us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/vacant-sync:latest
```

### 3. 変数の設定とTerraformのフル適用

`terraform/terraform.tfvars.example`を参考に、機密情報以外の変数を設定します。**機密情報（`db_password`, `places_api_key`）は`terraform.tfvars`に平文で記載しないでください。**

```bash
export TF_VAR_db_password="..."
export TF_VAR_places_api_key="..."
```

```bash
cd terraform
terraform validate
terraform plan \
  -var="project_id=<your-project-id>" \
  -var="app_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/api:latest" \
  -var="inference_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/infer:latest" \
  -var="vacant_sync_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/vacant-sync:latest" \
  -var="storage_bucket_name=<bucket-name>" \
  -out=tfplan
terraform apply tfplan
```

### 4. マイグレーションの適用

Cloud SQLインスタンス作成後、`migrations/001_init_schema.sql`を適用します。

```bash
psql "$DATABASE_URL" -f ../migrations/001_init_schema.sql
```

### 5. GitHub ActionsからのWorkload Identity Federationを有効化する

初回のフル適用が完了したら、`enable_github_actions_wif = true`・`github_repository = "org-name/repo-name"`を指定して再度`terraform apply`し、WIFプール・プロバイダ・デプロイ用サービスアカウントを作成します。

```bash
terraform apply \
  -var="project_id=<your-project-id>" \
  -var="app_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/api:latest" \
  -var="inference_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/infer:latest" \
  -var="vacant_sync_image=us-central1-docker.pkg.dev/<your-project-id>/regional-revitalization/vacant-sync:latest" \
  -var="storage_bucket_name=<bucket-name>" \
  -var="enable_github_actions_wif=true" \
  -var="github_repository=<org-name>/<repo-name>"
```

適用後、以下の出力値を確認します。

```bash
terraform output github_actions_workload_identity_provider
terraform output github_actions_deployer_service_account_email
```

### 6. GitHub Secrets / Variablesの設定

GitHubリポジトリの `Settings > Secrets and variables > Actions` で、値の機密性に応じてSecretsとVariablesの2つのタブに分けて登録します。プロジェクトID・サービスアカウントのメールアドレス・バケット名等、値自体に秘匿性が無い識別子は**Variables**に、DBパスワード・Places APIキー等の真に機密な値は**Secrets**に登録します。

**Variablesタブに登録するもの**

| Variable名 | 値 | 用途 |
|---|---|---|
| `GCP_PROJECT_ID` | GCPプロジェクトID | `deploy.yml`内の各コマンドで使用 |
| `GCP_DEPLOYER_SERVICE_ACCOUNT` | 手順5の`github_actions_deployer_service_account_email`出力値 | `google-github-actions/auth`アクションのなりすまし対象サービスアカウント |
| `GCP_BUCKET_NAME` | 手順1で作成したtfstate/地域資源ファイル共用バケット名 | `terraform init`のバックエンド設定、および`terraform apply`の`storage_bucket_name`変数 |

**Secretsタブに登録するもの**

| Secret名 | 値 | 用途 |
|---|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | 手順5の`github_actions_workload_identity_provider`出力値 | `google-github-actions/auth`アクションの認証設定（プールIDにプロジェクト番号を含むため機密扱いとする） |
| `TF_VAR_DB_PASSWORD` | Cloud SQLアプリ用DBパスワード | `terraform apply`の`db_password`変数 |
| `PLACES_API_KEY` | Google Maps Platform Places APIキー | `terraform apply`の`places_api_key`変数 |

サービスアカウントキー（JSON）は一切登録しません。GitHub ActionsはWorkload Identity Federationにより、実行時に発行される短命なOIDCトークンをGCPの短命な認証情報に交換して認証します。

### 7. 動作確認

- APIRunのヘルスチェック（例: `GET /docs`でFastAPIのSwagger UIが表示されることを確認）
- `POST /consultations`・`POST /resources`・`POST /vacant-properties/search`の簡易リクエスト
- Cloud Schedulerが居抜き物件同期サービス（Cloud Run Jobs）を定期実行することの確認

## 継続的デプロイ（GitHub Actions）

初回セットアップ完了後は、`main`ブランチへのpush（`src/`, `terraform/`, `migrations/`, `docker/`, `pyproject.toml`の変更を含む場合）をトリガーに、`.github/workflows/deploy.yml`が以下を自動実行します。

1. **デプロイ前テスト**（`ci.yml`を再利用ワークフローとして呼び出し）: `pytest`によるテスト、`terraform validate`、Dockerイメージのビルド確認（プッシュなし）
2. **コンテナイメージのビルド・プッシュ**: APIRun・InferRun・居抜き物件同期サービスの3イメージを、コミットSHAをタグとしてビルドし、Artifact Registryへプッシュ（`latest`タグも同時更新）
3. **Terraform適用**: 新しいイメージタグを`app_image`/`inference_image`/`vacant_sync_image`変数に渡し、`terraform plan`→`terraform apply`を実行

手動実行したい場合は、GitHub Actionsの「Actions」タブから`Deploy`ワークフローを選び、`Run workflow`（`workflow_dispatch`）で任意のブランチ・コミットに対して実行できます。

**プルリクエスト作成時**は`ci.yml`のみが実行され、実際のデプロイは行われません（`main`ブランチへのpush時のみ`deploy.yml`が動作します）。

## 機密情報の取り扱い方針

- `db_password`・`places_api_key`は`sensitive = true`が付与されているため、CLIの標準出力・`plan`差分表示には平文が表示されません。ただし、実際の値はこれらの変数からSecret Managerシークレットの初期バージョンとして書き込まれます。
- 最終的にDB接続情報・Places APIキーはSecret Manager（`google_secret_manager_secret_version`）に格納されます。各サービスはSecret Manager経由（Cloud Runの`secret_key_ref`）で環境変数として受け取り、コンテナイメージや設定ファイルに平文を書き込みません。
- Places APIキーへのSecret Managerアクセス権限（`roles/secretmanager.secretAccessor`）は、居抜き物件同期サービスの実行用サービスアカウントにのみ付与されます。APIRun・InferRunのサービスアカウントには付与されません。
- **tfstateに関する制約**: `sensitive = true`はCLI出力の抑制のみであり、値自体はtfstateファイルの属性値として保存されます（Terraformの一般的な制約）。運用時は以下を推奨します。
  - tfstateはリモートバックエンド（暗号化・アクセス制御されたGCSバケット等）に保存する
  - tfstateファイルへのアクセス権限を最小化する
  - 機密値のローテーションはSecret Manager側（`gcloud secrets versions add`等）で行い、Terraformの再適用による意図しない値の上書きを避ける
- **バケット統合とアクセス制限**: tfstateと地域資源ファイルは1つのGCSバケットに統合し、`terraform/state/`・`resources/`のプレフィックスで分離しています。APIRun実行用サービスアカウントには、IAM条件（Condition）により`resources/`プレフィックス配下のオブジェクトのみへのアクセス権限（`roles/storage.objectAdmin`）を付与し、tfstate（機密値の断片を含む）へは条件によりアクセスできません（`terraform/modules/storage/main.tf`参照）。

## モジュール概要

| モジュール | 内容 |
|---|---|
| `modules/network` | Serverless VPC Access コネクタ、Cloud SQLのプライベートIP接続に必要なPrivate Services Access（VPCピアリング） |
| `modules/cloudsql` | Cloud SQL for PostgreSQLインスタンス（プライベートIPのみ、`google_ml_integration`拡張有効化フラグ）、DB/ユーザー作成、DB接続情報のSecret Manager登録 |
| `modules/storage` | tfstateと共用の非公開Cloud Storageバケット（事前作成済みを参照）への、APIRun実行用サービスアカウント向けIAM条件付きアクセス権限（`resources/`プレフィックス限定） |
| `modules/cloudrun_app` | APIRun（アプリ本体サービス）のCloud Runサービス |
| `modules/cloudrun_inference` | InferRun（推論サービス、GPU L4、内部限定公開）のCloud Runサービス |
| `modules/cloudrun_jobs_vacant_property_sync` | 居抜き物件同期サービスのCloud Run Jobs、Places APIキーのSecret Manager登録・アクセス制御 |
| `modules/scheduler` | Cloud Schedulerによる定期トリガー（居抜き物件同期サービス起動） |
| `modules/artifact_registry` | コンテナイメージ格納用のArtifact Registry（Docker形式）リポジトリ |
| `modules/github_actions_wif` | GitHub ActionsからのWorkload Identity連携（プール・プロバイダ）、デプロイ用サービスアカウントと最小権限ロール付与（`enable_github_actions_wif=true`の場合のみ作成） |

## リージョンについて

すべてのリソースは`region`変数（デフォルト: `us-central1`）に従って作成されます。design.mdの方針（GPU L4はus-central1でホスト）に合わせてデフォルト値を`us-central1`としています。他リージョンへの変更は、推論サービスのGPU可用性の制約により推奨しません。

## デプロイ後の運用チェックリスト

- [ ] `terraform validate`・`terraform plan`で構文・変更内容を確認した
- [ ] Cloud SQLインスタンスにマイグレーション（`migrations/001_init_schema.sql`）を適用した
- [ ] Secret ManagerにDB接続情報・Places APIキーが正しく登録されていることを確認した
- [ ] InferRunが`allUsers`に公開されておらず、APIRunのサービスアカウントのみが呼び出せることを確認した
- [ ] Cloud Storageバケット（tfstate/地域資源ファイル共用）が非公開設定（`public_access_prevention = "enforced"`）になっていることを確認した
- [ ] APIRun実行用サービスアカウントのバケットIAM権限が、IAM条件により`resources/`プレフィックス配下に限定されていること（tfstateへアクセスできないこと）を確認した
- [ ] Cloud Schedulerのスケジュール（`vacant_sync_schedule`）が、監視対象place_id数とAPIレート制限を踏まえて30日以内に全件リフレッシュされる頻度になっていることを確認した
- [ ] tfstateの保存先（リモートバックエンド）とアクセス権限を確認した
- [ ] GitHub Actions Secretsにサービスアカウントキー（JSON）を登録していないこと（WIFのみで認証していること）を確認した
- [ ] GitHub Actionsのデプロイ用サービスアカウント（`github_actions_wif`モジュール）に、必要以上の権限（Owner/Editor等）が付与されていないことを確認した
- [ ] `attribute_condition`により、Workload Identity連携が想定するGitHubリポジトリ（`github_repository`変数）に限定されていることを確認した

## GitHub Actionsに関するトラブルシューティング

| 症状 | 想定原因 | 対処 |
|---|---|---|
| `terraform-apply`ジョブで`Error 403: Permission denied` | デプロイ用サービスアカウントに必要なロールが不足している | `terraform/modules/github_actions_wif/main.tf`の`local.deployer_roles`に必要なロールを追加し再適用する |
| `google-github-actions/auth`ステップで認証失敗 | `GCP_WORKLOAD_IDENTITY_PROVIDER`（Secrets）・`GCP_DEPLOYER_SERVICE_ACCOUNT`（Variables）の値が誤っている、または`attribute_condition`のリポジトリ名が不一致 | SecretsとVariablesの値を`terraform output`の値と再度突き合わせる。`github_repository`変数がリポジトリ名（`org-name/repo-name`）と完全一致しているか確認する |
| `terraform init`で`Error: Backend configuration changed` | tfstateバケット名の変更、またはローカルとCIで異なるバックエンド設定を使っている | `-reconfigure`オプション付きで`terraform init`を実行するか、バックエンド設定を統一する |
| Dockerイメージのビルドが失敗する | `pyproject.toml`の依存関係変更がDockerfileのキャッシュと整合していない | `docker/*/Dockerfile`の`pip install`対象を確認し、必要なエクストラ（`api`, `postgres`, `gcs`等）が指定されているか確認する |

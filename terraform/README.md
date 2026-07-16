# Terraform構成: 地方創生支援システム

本ディレクトリは、`design.md`「コンポーネント6: IaC (Terraform)」および
Requirements 7.1, 8.4, 9.1, 10.1〜10.3, 13.6に基づき作成した、
地方創生支援システム（regional-revitalization-support-system）のGCPインフラを
コード化したTerraform構成である。

## 重要な注記: 実行検証について

**本コードは、Terraform CLIが利用できない開発環境で作成された。**
そのため、`terraform init` / `terraform validate` / `terraform plan` /
`terraform apply` による実際の実行検証は、本フェーズでは行っていない。
構文・構造の妥当性はコードレビューレベルでのみ確認済みである。

実際の`init`/`validate`/`plan`/`apply`は、Terraform CLI（および`gcloud`認証、
対象GCPプロジェクトへの権限）が利用可能な別環境で実施する必要がある。
適用前に必ず以下を行うこと。

1. `terraform init` でプロバイダを初期化する
2. `terraform validate` で構文エラーがないことを確認する
3. `terraform plan` で作成される変更内容を確認する
4. 内容に問題がなければ `terraform apply` を実行する

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
    ├── cloudrun_frontend/                     # 動作確認用フロント画面(inuki、未認証で誰でもアクセス可能)
    ├── cloudrun_jobs_vacant_property_sync/    # 居抜き物件同期サービス(Cloud Run Jobs) + Secret Manager(Places APIキー)
    └── scheduler/                             # Cloud Scheduler(定期トリガー)
```

## 前提条件

- 既にプロビジョニング済みのGCPプロジェクトが存在すること（`tasks.md`のNotes参照）
- 課金設定が有効化されていること
- 実行するTerraformの認証情報（サービスアカウントまたはユーザー認証）に、
  Cloud Run/Cloud SQL/Cloud Storage/VPC Access/Secret Manager/Cloud Scheduler/
  IAM/Service Usageに対する十分な権限があること
- 対象GCPプロジェクトで以下のAPIが有効化可能であること（`main.tf`内で
  `google_project_service`により有効化を試みるが、組織ポリシーにより
  制限される場合は事前に有効化しておくこと）
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

## 必要な変数一覧

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `project_id` | ○ | - | GCPプロジェクトID |
| `region` | - | `us-central1` | 全リソースの作成リージョン（変更しないこと） |
| `environment` | - | `dev` | 環境識別子（リソース名サフィックス） |
| `app_service_name` | - | `regional-revitalization-api` | APIRunのCloud Runサービス名 |
| `app_image` | ○ | - | APIRunのコンテナイメージURL |
| `inference_service_name` | - | `inuki-gemma4` | InferRun(Gemma 4搭載)のCloud Runサービス名 |
| `inference_image` | ○ | - | InferRunのコンテナイメージURL |
| `frontend_service_name` | - | `inuki` | 動作確認用フロント画面(inuki)のCloud Runサービス名 |
| `frontend_image` | ○ | - | inukiのコンテナイメージURL(nginxで`frontend/index.html`を配信) |
| `admin_initial_username` | - | `admin` | 管理画面(/admin/)の初回管理者アカウントのログインID |
| `admin_initial_password` | ○（機密） | - | 管理画面の初回管理者アカウントのパスワード(8文字以上) |
| `admin_places_api_key` | - | `""` | 管理画面の「この場所でGoogle Places APIを検索する」機能用APIキー。空文字列の場合は機能無効(モッククライアントのまま動作) |
| `vacant_sync_job_name` | - | `vacant-property-sync` | 居抜き物件同期サービスのCloud Run Jobs名 |
| `vacant_sync_image` | ○ | - | 居抜き物件同期サービスのコンテナイメージURL |
| `vpc_network_name` | - | `default` | VPCコネクタを紐づける対象VPCネットワーク名 |
| `vpc_connector_cidr` | - | `10.8.0.0/28` | VPCアクセスコネクタのCIDR範囲(/28) |
| `db_instance_name` | - | `regional-revitalization-db` | Cloud SQLインスタンス名 |
| `db_tier` | - | `db-f1-micro` | Cloud SQLのマシンタイプ（コスト優先の共有コア） |
| `db_name` | - | `regional_revitalization` | アプリケーション用DB名 |
| `db_user` | - | `app_user` | アプリケーション用DBユーザー名 |
| `db_password` | ○（機密） | - | アプリケーション用DBユーザーのパスワード |
| `storage_bucket_name` | ○ | - | tfstateと共用するバケット名（グローバル一意、`resources/`プレフィックス配下を地域資源ファイル用に使用） |
| `places_api_key` | ○（機密） | - | Google Maps Platform Places APIキー |
| `vacant_sync_schedule` | - | `0 3 * * *` | 同期サービスの実行スケジュール(unix-cron) |
| `vacant_sync_time_zone` | - | `Etc/UTC` | スケジュールのタイムゾーン |
| `labels` | - | `{app = "regional-revitalization"}` | 全リソース共通ラベル |
| `artifact_registry_repository_id` | - | `regional-revitalization` | コンテナイメージを格納するArtifact Registryリポジトリ名 |
| `enable_github_actions_wif` | - | `false` | GitHub Actions用のWorkload Identity連携（プール・プロバイダ・デプロイ用サービスアカウント）を作成するかどうか。初回は`false`で適用し、人間の管理者権限で作成した後に`true`へ切り替える運用を想定する |
| `github_repository` | - | `""` | GitHub ActionsからのWIF認証を許可するGitHubリポジトリ（`"org-name/repo-name"`形式）。`enable_github_actions_wif=true`の場合に使用する |

`db_password`・`places_api_key`は`sensitive = true`を付与しているため、
CLIの標準出力・`plan`差分表示には平文が表示されない。ただし、実際の値は
これらの変数からSecret Managerシークレットの初期バージョンとして書き込まれる。

## 機密情報の取り扱い方針

- `db_password`・`places_api_key`は**`terraform.tfvars`に平文で記載しないこと**。
  `terraform.tfvars.example`を参考にしつつ、実行時は環境変数
  (`TF_VAR_db_password`, `TF_VAR_places_api_key`)またはCI/CDのシークレット
  ストアから注入すること
- 上記2つの機密変数はDB接続情報／Places APIキーとして最終的に
  Secret Manager（`google_secret_manager_secret_version`）に格納される。
  アプリケーション（APIRun/InferRun/居抜き物件同期サービス）はSecret Manager
  経由（Cloud Runの`secret_key_ref`）でこれらの値を環境変数として受け取り、
  コンテナイメージや設定ファイルに平文を書き込まない
- Places APIキーへのSecret Managerアクセス権限（`roles/secretmanager.secretAccessor`）は、
  居抜き物件同期サービスの実行用サービスアカウントにのみ付与する
  （`modules/cloudrun_jobs_vacant_property_sync/main.tf`）。APIRun/InferRunの
  サービスアカウントには付与しない
- `admin_initial_password`（管理画面の初回管理者パスワード）も同様に
  `terraform.tfvars`に平文で記載せず、環境変数`TF_VAR_admin_initial_password`
  またはCI/CDのシークレットストア（GitHub Secretsの`ADMIN_INITIAL_PASSWORD`）
  から注入すること。この値はAPIRunが起動時に管理ユーザーが0件の場合のみ
  読み取り、初回管理者アカウントを自動作成する（`api.py`の
  `_bootstrap_initial_admin_user()`）。2件目以降の管理ユーザーは、
  管理画面のユーザー管理ページ（`/admin/users.html`）から作成する
- **GitHub ActionsでCI/CDデプロイする場合、以下のSecretsを事前にリポジトリに
  登録しておく必要がある**（未設定のまま`deploy.yml`を実行すると、値が空文字列
  として渡され`admin_initial_password`は`validation`エラーで即座に検出される。
  `admin_places_api_key`は空文字列でも動作するオプトイン機能のため、未設定でも
  applyは失敗しない）:
  - `ADMIN_INITIAL_PASSWORD`（必須、8文字以上）
  - `ADMIN_PLACES_API_KEY`（任意。設定しない場合、管理画面のPlaces APIリアル
    タイム検索機能はモッククライアントのまま動作し、実際のAPI呼び出しは
    行われない）
- **tfstateに関する制約**: `sensitive = true`はCLI出力の抑制のみであり、
  値自体はtfstateファイルの属性値として保存される。これはTerraformの一般的な
  制約である。運用時は以下を推奨する:
  - tfstateはリモートバックエンド（GCSバケット）に保存する。`versions.tf`で
    `backend "gcs" { prefix = "terraform/state" }`として部分バックエンド構成
    を定義済みであり、`terraform init -backend-config="bucket=<バケット名>"`
    実行時にバケット名を指定する（バケット自体はTerraform管理外で事前に
    作成する。詳細は`docs/deployment-guide.md`の初回セットアップ手順を参照）
  - tfstateファイルへのアクセス権限を最小化する
  - 機密値のローテーションはSecret Manager側（`gcloud secrets versions add`等）
    で行い、Terraformの再適用による意図しない値の上書きを避ける運用も検討する

## リージョンについて

すべてのリソースは`region`変数（デフォルト: `us-central1`）に従って作成される。
design.mdの方針（GPU L4はus-central1でホスト）に合わせ、デフォルト値を
`us-central1`としている。他リージョンへの変更は推論サービスのGPU可用性の
制約により推奨しない。

## モジュール概要

- `modules/network`: Serverless VPC Access コネクタ、およびCloud SQLの
  プライベートIP接続に必要なPrivate Services Access(VPCピアリング)
- `modules/cloudsql`: Cloud SQL for PostgreSQLインスタンス（プライベートIPのみ、
  `google_ml_integration`拡張有効化フラグ）、DB/ユーザー作成、
  DB接続情報のSecret Manager登録
- `modules/storage`: tfstateと共用の非公開Cloud Storageバケット（Terraform管理外で
  事前作成、`resources/`プレフィックス配下）への、APIRun実行用サービスアカウント
  向けIAM条件付きアクセス権限（`resources/`プレフィックス限定、`roles/storage.objectAdmin`）
- `modules/cloudrun_app`: APIRun（アプリ本体サービス）のCloud Runサービス
- `modules/cloudrun_inference`: InferRun（推論サービス、GPU L4、内部限定公開）の
  Cloud Runサービス
- `modules/cloudrun_frontend`: inuki（動作確認用フロント画面、`frontend/index.html`を
  nginxで配信）のCloud Runサービス。APIRun/InferRunとは異なり、`allUsers`に
  `roles/run.invoker`を付与し常時未認証公開する。組織側の組織ポリシー制約
  （`constraints/iam.allowedPolicyMemberDomains`）がドメイン限定のままだと
  IAMバインディング作成が`FAILED_PRECONDITION`で失敗するため、対象プロジェクトに
  限定して制約をALLOW_ALLへ上書きしておく必要がある
  （`gcloud resource-manager org-policies set-policy`）
- `modules/cloudrun_jobs_vacant_property_sync`: 居抜き物件同期サービスの
  Cloud Run Jobs、Places APIキーのSecret Manager登録・アクセス制御
- `modules/scheduler`: Cloud Schedulerによる定期トリガー（居抜き物件同期サービス起動）
- `modules/artifact_registry`: コンテナイメージ格納用のArtifact Registry
  （Docker形式）リポジトリ
- `modules/github_actions_wif`: GitHub ActionsからのWorkload Identity連携
  （プール・プロバイダ）、デプロイ用サービスアカウントと最小権限ロール付与
  （`enable_github_actions_wif=true`の場合のみ作成）

## GitHub ActionsによるCI/CD

本リポジトリは`.github/workflows/ci.yml`（テスト・構文検証）と
`.github/workflows/deploy.yml`（ビルド・デプロイ）を用いてCI/CDパイプラインを
構築している。GCPへの認証はサービスアカウントキー（JSON）を使わず、
Workload Identity Federation（キーレス認証）で行う。

`deploy.yml`内では、プロジェクトID・デプロイ用サービスアカウント・バケット名等、
値自体に秘匿性の無い識別子はリポジトリの Variables（`vars.*`）から、
DBパスワード・Places APIキー・Workload Identityプロバイダ名等の機密値は
Secrets（`secrets.*`）から参照する。

初回セットアップ手順（tfstateと地域資源ファイル共用バケットの作成、WIFの有効化、
GitHub Secrets/Variablesの設定）の詳細は`docs/deployment-guide.md`を参照すること。

## コーディング規約

本Terraformコードのコメントはすべて日本語で記述し、ファイルはUTF-8エンコーディング・
LF改行コードで保存している（Requirements 11参照）。

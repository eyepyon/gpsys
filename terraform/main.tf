# ルート構成
#
# design.md「コンポーネント6: IaC (Terraform)」「Dependencies」章に基づき、
# 各モジュールを呼び出してGCPリソース一式（Cloud Run x2、Cloud Run Jobs、
# Cloud Scheduler、Cloud SQL、Cloud Storage、VPCコネクタ、IAM、Secret Manager）
# をus-central1リージョンにプロビジョニングする。
#
# 【重要】本コードはTerraform CLIが利用できない開発環境で作成されたため、
# `terraform init`/`validate`/`plan`による実行検証は行っていない。
# 実際の適用前には、Terraform CLIが利用可能な環境で検証すること
# （詳細はREADME.mdを参照）。

# --- 必要なAPIの有効化 ---
locals {
  required_apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "cloudscheduler.googleapis.com",
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    # IAM Service Account Credentials API。Workload Identity Federation経由の
    # なりすまし（impersonation、`generateAccessToken`/`iam.serviceAccounts.
    # getAccessToken`権限）に必須。有効化されていないと`roles/iam.
    # workloadIdentityUser`を付与済みでも`google-github-actions/auth`の
    # トークン取得がPERMISSION_DENIEDになる。
    "iamcredentials.googleapis.com",
    # Artifact Registry API。コンテナイメージのpull/push（docker
    # push/pull、`google_artifact_registry_repository`の作成・利用）に必須。
    # 有効化されていないと`docker push`が
    # 「Artifact Registry API has not been used...」で失敗する。
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each                   = toset(local.required_apis)
  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}

# --- artifact_registry: コンテナイメージ格納用リポジトリ ---
module "artifact_registry" {
  source = "./modules/artifact_registry"

  project_id    = var.project_id
  region        = var.region
  repository_id = var.artifact_registry_repository_id
  labels        = var.labels

  depends_on = [google_project_service.apis]
}

# --- github_actions_wif: GitHub ActionsからのキーレスCI/CDデプロイ用WIF ---
#
# 【重要・初回適用に関する注記】本モジュールが作成するデプロイ用サービス
# アカウント自体をGitHub Actionsが利用してTerraformを適用する構成のため、
# 「初回」はGCPプロジェクトへの十分な権限を持つ人間の管理者が
# ローカル環境（または信頼できるCI環境）から`terraform apply`を実行し、
# WIFプールとデプロイ用サービスアカウントを作成する必要がある。
# 2回目以降は、GitHub Actionsのワークフローがこのデプロイ用サービス
# アカウントになりすまして（impersonate）Terraformを適用できる。
# 詳細はdocs/deployment-guide.mdまたはterraform/README.mdを参照。
module "github_actions_wif" {
  count = var.enable_github_actions_wif ? 1 : 0

  source = "./modules/github_actions_wif"

  project_id        = var.project_id
  github_repository = var.github_repository

  depends_on = [google_project_service.apis]
}

# --- network: VPCコネクタ + Private Services Access ---
module "network" {
  source = "./modules/network"

  project_id    = var.project_id
  region        = var.region
  network_name  = var.vpc_network_name
  ip_cidr_range = var.vpc_connector_cidr
  # VPCコネクタ名はGCPの制約で最大25文字（^[a-z][-a-z0-9]{0,23}[a-z0-9]$）。
  # "regional-revit-connector-${var.environment}"（例: "regional-revit-connector-dev"）
  # は29文字となり超過するため、短縮した名前を使用する。
  connector_name = "rr-connector-${var.environment}"

  depends_on = [google_project_service.apis]
}

# --- cloudsql: Cloud SQL for PostgreSQL ---
module "cloudsql" {
  source = "./modules/cloudsql"

  project_id             = var.project_id
  region                 = var.region
  instance_name          = "${var.db_instance_name}-${var.environment}"
  tier                   = var.db_tier
  db_name                = var.db_name
  db_user                = var.db_user
  db_password            = var.db_password
  network_self_link      = module.network.network_self_link
  private_vpc_connection = module.network.private_vpc_connection
  labels                 = var.labels

  depends_on = [google_project_service.apis]
}

# --- storage: 地域資源ファイル保存用バケット ---
#
# 【重要】本バケットはTerraformのtfstate保存先バケットと共用する
# （`resources/`プレフィックス配下を地域資源ファイル用に使用する）。
# バケット自体はTerraform管理外で事前作成されたものを参照するのみであり、
# 新規作成は行わない（詳細はmodules/storage/main.tf、
# docs/deployment-guide.mdの初回セットアップ手順を参照）。
module "storage" {
  source = "./modules/storage"

  bucket_name                   = var.storage_bucket_name
  app_run_service_account_email = google_service_account.app_run_sa.email
}

# --- APIRunの実行用サービスアカウント ---
#
# cloudrun_app / cloudrun_inference の両モジュールがこのサービスアカウントを
# 参照する（cloudrun_appは実行アイデンティティとして、cloudrun_inferenceは
# invoker権限の付与先として）ため、モジュール間の循環参照を避けるべく
# ルート構成側で作成する。
# サービスアカウントのaccount_idはGCPの制約で6〜30文字である必要がある。
# `${var.app_service_name}-sa-${var.environment}`
# （例: "regional-revitalization-api-sa-dev"）は30文字を超えるため、
# 短縮した固定のaccount_idを使用する。
resource "google_service_account" "app_run_sa" {
  project      = var.project_id
  account_id   = "api-run-sa-${var.environment}"
  display_name = "APIRun (アプリ本体サービス) 実行用サービスアカウント"
}

# --- cloudrun_inference: 推論サービス (InferRun, GPU L4) ---
module "cloudrun_inference" {
  source = "./modules/cloudrun_inference"

  project_id                    = var.project_id
  region                        = var.region
  service_name                  = "${var.inference_service_name}-${var.environment}"
  service_account_id            = "infer-run-sa-${var.environment}"
  image                         = var.inference_image
  vpc_connector_id              = module.network.connector_id
  invoker_service_account_email = google_service_account.app_run_sa.email
  labels                        = var.labels
}

# --- 管理画面(/admin/)の初回管理者パスワード用シークレット ---
#
# db_password/places_api_keyと同様に、値自体はSecret Manager登録用の
# 一時的な入力としてのみ受け渡す（terraform.tfvarsに平文で記載しないこと。
# 詳細はterraform/README.mdの「機密情報の取り扱い方針」を参照）。
resource "google_secret_manager_secret" "admin_initial_password" {
  project   = var.project_id
  secret_id = "admin-initial-password-${var.environment}"

  replication {
    auto {}
  }

  labels = var.labels

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "admin_initial_password" {
  secret      = google_secret_manager_secret.admin_initial_password.id
  secret_data = var.admin_initial_password
}

# --- cloudrun_app: アプリ本体サービス (APIRun) ---
module "cloudrun_app" {
  source = "./modules/cloudrun_app"

  project_id                        = var.project_id
  region                            = var.region
  service_name                      = "${var.app_service_name}-${var.environment}"
  service_account_email             = google_service_account.app_run_sa.email
  image                             = var.app_image
  vpc_connector_id                  = module.network.connector_id
  db_connection_secret_id           = module.cloudsql.db_connection_secret_id
  inference_service_url             = module.cloudrun_inference.service_url
  storage_bucket_name               = module.storage.bucket_name
  allow_unauthenticated             = var.app_allow_unauthenticated
  cors_allowed_origins              = var.app_cors_allowed_origins
  admin_initial_username            = var.admin_initial_username
  admin_initial_password_secret_id  = google_secret_manager_secret.admin_initial_password.secret_id
  labels                            = var.labels
}

# --- cloudrun_frontend: 動作確認用フロント画面 (inuki) ---
#
# APIRun/InferRunとは別サービスとして、どこからでも未認証でアクセスできる
# 静的サイト配信用Cloud Runを用意する。allUsersへのIAM権限付与を可能にする
# ため、事前にプロジェクト側の組織ポリシー制約
# （constraints/iam.allowedPolicyMemberDomains）をALLOW_ALLに設定しておく
# 必要がある（詳細はterraform/README.md参照）。
module "cloudrun_frontend" {
  source = "./modules/cloudrun_frontend"

  project_id         = var.project_id
  region             = var.region
  service_name       = var.frontend_service_name
  service_account_id = "inuki-sa-${var.environment}"
  image              = var.frontend_image
  labels             = var.labels

  depends_on = [google_project_service.apis]
}

# --- cloudrun_jobs_vacant_property_sync: 居抜き物件同期サービス ---
module "vacant_property_sync" {
  source = "./modules/cloudrun_jobs_vacant_property_sync"

  project_id              = var.project_id
  region                  = var.region
  job_name                = "${var.vacant_sync_job_name}-${var.environment}"
  image                   = var.vacant_sync_image
  vpc_connector_id        = module.network.connector_id
  db_connection_secret_id = module.cloudsql.db_connection_secret_id
  places_api_key          = var.places_api_key
  labels                  = var.labels

  depends_on = [google_project_service.apis]
}

# --- scheduler: 居抜き物件同期サービスの定期トリガー ---
module "scheduler" {
  source = "./modules/scheduler"

  project_id         = var.project_id
  region             = var.region
  scheduler_job_name = "${var.vacant_sync_job_name}-trigger-${var.environment}"
  service_account_id = "vacant-sync-sched-sa-${var.environment}"
  schedule           = var.vacant_sync_schedule
  time_zone          = var.vacant_sync_time_zone
  target_job_name    = module.vacant_property_sync.job_name
}

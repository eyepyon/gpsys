# github_actions_wifモジュール
#
# GitHub ActionsからGCPへキーレスで認証するためのWorkload Identity連携
# （Workload Identity Federation, WIF）を構築する。
#
# 【セキュリティ方針】
# - サービスアカウントキー（JSON）は発行しない。GitHub Actionsのワークフロー
#   実行時に発行される短命なOIDCトークンを、Workload Identityプール経由で
#   GCPの短命な認証情報に交換する（`google-github-actions/auth`アクション想定）。
# - `attribute_condition`により、認証を許可するGitHubリポジトリを
#   `var.github_repository`（例: "org-name/repo-name"）に限定する。
#   他リポジトリからの詐称を防ぐため、リポジトリ名は完全一致で照合する。
# - デプロイ用サービスアカウント（`deployer`）には、Terraform適用・
#   コンテナイメージのpush・Cloud Run/Cloud Run Jobsの更新に必要な最小限の
#   ロールのみを付与する（プロジェクト全体のOwner/Editorロールは付与しない）。

resource "google_iam_workload_identity_pool" "github_actions" {
  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "GitHub ActionsからのCI/CDデプロイ用Workload Identityプール"
}

resource "google_iam_workload_identity_pool_provider" "github_actions" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_actions.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # 認証を許可するGitHubリポジトリを完全一致で限定する（他リポジトリからの
  # トークンでの認証を拒否する）。
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# --- デプロイ用サービスアカウント ---
#
# GitHub Actionsのワークフローが実行するTerraform apply・コンテナイメージの
# push・Cloud Run/Cloud Run Jobsのデプロイ操作を行うための専用サービス
# アカウント。プロジェクト全体のOwner/Editorロールは付与せず、必要な
# ロールのみを個別に付与する（下記IAMバインディング参照）。
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = var.deployer_service_account_id
  display_name = "GitHub Actions デプロイ用サービスアカウント"
}

# GitHubリポジトリ（`var.github_repository`）からのWorkload Identityによる
# なりすまし（impersonation）を、上記デプロイ用サービスアカウントに限定して許可する。
resource "google_service_account_iam_member" "deployer_workload_identity_binding" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions.name}/attribute.repository/${var.github_repository}"
}

# --- デプロイ用サービスアカウントへの最小権限ロール付与 ---
#
# Terraform apply（Cloud Run/Cloud SQL/Cloud Storage/VPC/Secret Manager/
# Scheduler/IAM各リソースの作成・更新）、およびArtifact Registryへの
# イメージpushに必要なロールを付与する。
locals {
  deployer_roles = [
    "roles/run.admin",                       # Cloud Run / Cloud Run Jobsのデプロイ
    "roles/cloudsql.admin",                  # Cloud SQLインスタンスの管理
    "roles/storage.admin",                   # Cloud Storageバケットの管理
    "roles/secretmanager.admin",             # Secret Managerシークレットの管理
    "roles/artifactregistry.writer",         # コンテナイメージのpush
    "roles/cloudscheduler.admin",            # Cloud Schedulerジョブの管理
    "roles/vpcaccess.admin",                 # 既存環境との互換性維持（Direct VPC移行後に別途削除可能）
    "roles/iam.serviceAccountUser",          # Cloud Run実行用サービスアカウントの利用
    "roles/iam.serviceAccountAdmin",         # 各サービス実行用サービスアカウントの作成・IAM設定
    "roles/servicenetworking.networksAdmin", # Private Services Access(VPCピアリング)の管理
    "roles/compute.networkAdmin",            # VPCネットワーク関連リソースの管理
    "roles/serviceusage.serviceUsageAdmin",  # 必要なAPIの有効化
  ]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(local.deployer_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

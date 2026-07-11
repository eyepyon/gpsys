# github_actions_wifモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "github_repository" {
  description = "認証を許可するGitHubリポジトリ（\"org-name/repo-name\"形式の完全一致で照合する）"
  type        = string
}

variable "pool_id" {
  description = "Workload Identityプールの識別子"
  type        = string
  default     = "github-actions-pool"
}

variable "provider_id" {
  description = "Workload Identityプロバイダの識別子"
  type        = string
  default     = "github-actions-provider"
}

variable "deployer_service_account_id" {
  description = "デプロイ用サービスアカウントのaccount_id"
  type        = string
  default     = "github-actions-deployer"
}

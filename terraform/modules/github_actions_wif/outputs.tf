# github_actions_wifモジュール出力値

output "workload_identity_provider" {
  description = "GitHub Actionsの`google-github-actions/auth`アクションに渡すWorkload Identityプロバイダの完全なリソース名"
  value       = google_iam_workload_identity_pool_provider.github_actions.name
}

output "deployer_service_account_email" {
  description = "GitHub Actionsがなりすます(impersonate)デプロイ用サービスアカウントのメールアドレス"
  value       = google_service_account.deployer.email
}

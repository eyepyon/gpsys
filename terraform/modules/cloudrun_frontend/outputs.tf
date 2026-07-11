# cloudrun_frontendモジュール出力値

output "service_name" {
  description = "作成したinuki Cloud Runサービス名"
  value       = google_cloud_run_v2_service.frontend.name
}

output "service_url" {
  description = "inukiのURL（誰でも未認証でアクセス可能）"
  value       = google_cloud_run_v2_service.frontend.uri
}

output "service_account_email" {
  description = "inuki実行用サービスアカウントのメールアドレス"
  value       = google_service_account.frontend_run_sa.email
}

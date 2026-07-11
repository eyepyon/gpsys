# cloudrun_appモジュール出力値

output "service_name" {
  description = "作成したAPIRun Cloud Runサービス名"
  value       = google_cloud_run_v2_service.app.name
}

output "service_url" {
  description = "APIRunのURL"
  value       = google_cloud_run_v2_service.app.uri
}

output "service_account_email" {
  description = "APIRun実行用サービスアカウントのメールアドレス（本モジュールへの入力値をそのまま出力する）"
  value       = var.service_account_email
}

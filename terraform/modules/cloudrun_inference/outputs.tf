# cloudrun_inferenceモジュール出力値

output "service_name" {
  description = "作成したInferRun Cloud Runサービス名"
  value       = google_cloud_run_v2_service.inference.name
}

output "service_url" {
  description = "InferRunの内部URL（APIRunからの呼び出し先）"
  value       = google_cloud_run_v2_service.inference.uri
}

output "service_account_email" {
  description = "InferRun実行用サービスアカウントのメールアドレス"
  value       = google_service_account.infer_run_sa.email
}

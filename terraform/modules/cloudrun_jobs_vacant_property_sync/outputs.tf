# cloudrun_jobs_vacant_property_syncモジュール出力値

output "job_name" {
  description = "作成した居抜き物件同期サービスのCloud Run Jobs名"
  value       = google_cloud_run_v2_job.vacant_sync.name
}

output "job_id" {
  description = "作成したCloud Run JobsのリソースID（Cloud Schedulerのターゲット指定に使用する）"
  value       = google_cloud_run_v2_job.vacant_sync.id
}

output "service_account_email" {
  description = "居抜き物件同期サービス実行用サービスアカウントのメールアドレス"
  value       = google_service_account.vacant_sync_sa.email
}

output "places_api_key_secret_id" {
  description = "Places APIキーを格納したSecret ManagerシークレットのID"
  value       = google_secret_manager_secret.places_api_key.secret_id
}

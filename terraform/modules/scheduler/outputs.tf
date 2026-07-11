# schedulerモジュール出力値

output "scheduler_job_name" {
  description = "作成したCloud Schedulerジョブ名"
  value       = google_cloud_scheduler_job.vacant_sync_trigger.name
}

output "scheduler_service_account_email" {
  description = "Cloud Scheduler実行用サービスアカウントのメールアドレス"
  value       = google_service_account.scheduler_sa.email
}

# schedulerモジュール
#
# design.md「フロー3: 居抜き物件の同期・検知」に基づき、Cloud Schedulerにより
# 居抜き物件同期サービス（Cloud Run Jobs）を定期的（例: 日次）にトリガーする。
#
# Cloud SchedulerからCloud Run Jobsを起動するには、対象ジョブに対する
# `roles/run.invoker`権限を持つサービスアカウントが必要となるため、
# Cloud Scheduler専用のサービスアカウントを作成し、当該権限のみを付与する
# （最小権限の原則）。

resource "google_service_account" "scheduler_sa" {
  project      = var.project_id
  account_id   = "${var.scheduler_job_name}-sa"
  display_name = "Cloud Scheduler (居抜き物件同期トリガー) 実行用サービスアカウント"
}

# Cloud SchedulerのサービスアカウントにCloud Run Jobs起動権限のみを付与する
resource "google_cloud_run_v2_job_iam_member" "scheduler_run_invoker" {
  project  = var.project_id
  location = var.region
  name     = var.target_job_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "vacant_sync_trigger" {
  project   = var.project_id
  region    = var.region
  name      = var.scheduler_job_name
  schedule  = var.schedule
  time_zone = var.time_zone

  # Places APIの利用規約上の制約（business_status等は概ね30日で再取得が必要）を
  # 踏まえ、既定では日次実行とする（design.md Dependencies章参照）。
  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${var.target_job_name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

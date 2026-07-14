# cloudrun_jobs_vacant_property_syncモジュール
#
# design.md「コンポーネント5: 居抜き物件同期サービス (VacantPropertySyncService)」
# 「フロー3: 居抜き物件の同期・検知」に基づき、Google Places API（Place Details API）
# を定期的に呼び出し、`CLOSED_PERMANENTLY`を検知したスポットをCloud SQLにUPSERTする
# バッチ処理を、Cloud Run Jobsとして構成する。
#
# Requirements 13.6 / Security Considerations「Places APIキーの管理」に基づき、
# Places APIキーはSecret Managerに格納し、本ジョブの実行用サービスアカウントにのみ
# アクセス権限（`roles/secretmanager.secretAccessor`）を付与する
# （他のコンポーネント: APIRun/InferRunからは参照不可）。

resource "google_service_account" "vacant_sync_sa" {
  project      = var.project_id
  account_id   = "${var.job_name}-sa"
  display_name = "居抜き物件同期サービス (VacantPropertySyncService) 実行用サービスアカウント"
}

# --- Secret Manager: Places APIキー ---
resource "google_secret_manager_secret" "places_api_key" {
  project   = var.project_id
  secret_id = "${var.job_name}-places-api-key"

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_version" "places_api_key" {
  secret      = google_secret_manager_secret.places_api_key.id
  secret_data = var.places_api_key
}

# Places APIキーへのアクセスは、居抜き物件同期サービスの実行用サービスアカウントにのみ
# 付与する。他のサービスアカウント（APIRun/InferRun）には付与しないことで、
# 「当該サービスにのみアクセス権限を付与する」という要件を満たす。
resource "google_secret_manager_secret_iam_member" "vacant_sync_places_key_access" {
  secret_id = google_secret_manager_secret.places_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vacant_sync_sa.email}"
}

# DB接続情報シークレットへの読み取り権限も、本サービスの実行用サービスアカウントに付与する
resource "google_secret_manager_secret_iam_member" "vacant_sync_db_secret_access" {
  secret_id = var.db_connection_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vacant_sync_sa.email}"
}

resource "google_cloud_run_v2_job" "vacant_sync" {
  project  = var.project_id
  name     = var.job_name
  location = var.region

  # google_cloud_run_v2_jobの`deletion_protection`はデフォルトtrueであり、
  # 設定変更等でリソースの再作成（destroy→create）が必要になった場合、
  # 明示的にfalseにしていないとapply自体が
  # 「cannot destroy job without setting deletion_protection=false」で
  # 失敗する。本サービスは開発環境での運用を前提とし、環境変数・イメージ等の
  # 変更で再作成が発生しうるため、falseとする。
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.vacant_sync_sa.email
      max_retries     = var.max_retries
      timeout         = var.task_timeout

      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }

        # DB接続情報をSecret Manager経由で環境変数にマウントする
        env {
          name = "DB_CONNECTION_JSON"
          value_source {
            secret_key_ref {
              secret  = var.db_connection_secret_id
              version = "latest"
            }
          }
        }

        # Places APIキーをSecret Manager経由で環境変数にマウントする
        # （コンテナイメージやTerraformコードに平文で埋め込まない）
        env {
          name = "PLACES_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.places_api_key.secret_id
              version = "latest"
            }
          }
        }


        env {
          name  = "PLACES_API_ENABLED"
          value = tostring(var.places_api_enabled)
        }
      }
    }
  }
}

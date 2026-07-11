# cloudrun_appモジュール
#
# design.md「コンポーネント1: アプリ本体サービス (APIRun)」に基づき、
# 利用者からのHTTPリクエストを受け付けるCloud Runサービスを作成する。
# GPUを必要とする推論処理は別サービス（InferRun、cloudrun_inferenceモジュール）
# に分離し、本サービスはGPUなしの構成でコストを最適化する。

# 【注記】APIRun実行用サービスアカウントはルート構成（main.tf）側で作成し、
# `var.service_account_email`として受け取る。これは、InferRun（cloudrun_inference
# モジュール）がこのサービスアカウントに対してinvoker権限を付与する必要があり、
# 本モジュールでサービスアカウントを作成すると`cloudrun_app`⇔`cloudrun_inference`間で
# モジュールの循環参照が発生してしまうためである。

# DB接続情報シークレットへの読み取り権限をAPIRun実行用サービスアカウントに付与する
resource "google_secret_manager_secret_iam_member" "app_run_db_secret_access" {
  secret_id = var.db_connection_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_service" "app" {
  project  = var.project_id
  name     = var.service_name
  location = var.region

  # google_cloud_run_v2_serviceの`deletion_protection`はデフォルトtrueであり、
  # 設定変更等でリソースの再作成（destroy→create）が必要になった場合、
  # 明示的にfalseにしていないとapply自体が
  # 「cannot destroy service without setting deletion_protection=false」で
  # 失敗する。本サービスは開発環境での運用を前提とし、設定変更で再作成が
  # 発生しうるため、falseとする。
  deletion_protection = false

  # design.md Security Considerations: 「InferRunは`allUsers`に公開しない」
  # APIRunについても、原則としてIAM認証必須（未認証アクセス拒否）をデフォルトとする。
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = var.service_account_email

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

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

      env {
        name  = "GCS_BUCKET_NAME"
        value = var.storage_bucket_name
      }

      env {
        name  = "INFER_RUN_URL"
        value = var.inference_service_url
      }

      # 動作確認用フロント画面等、ブラウザから直接呼び出すオリジンを
      # 許可する場合にのみ設定する（未設定時はCORS無効のまま）。
      dynamic "env" {
        for_each = var.cors_allowed_origins != "" ? [var.cors_allowed_origins] : []
        content {
          name  = "CORS_ALLOWED_ORIGINS"
          value = env.value
        }
      }

      # DB接続情報はSecret Manager経由でJSON文字列として環境変数にマウントする
      # （平文の接続情報をコンテナイメージやTerraformコードに直接埋め込まない）
      env {
        name = "DB_CONNECTION_JSON"
        value_source {
          secret_key_ref {
            secret  = var.db_connection_secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

# 未認証アクセスを許可する場合のみ`allUsers`にinvoker権限を付与する。
# デフォルト（allow_unauthenticated=false）ではIAM認証必須の非公開サービスとなる。
resource "google_cloud_run_v2_service_iam_member" "allow_unauthenticated" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# cloudrun_frontendモジュール
#
# 動作確認用フロント画面（inuki）を配信するCloud Runサービスを作成する。
# APIRun/InferRunとは異なり、ブラウザから誰でも直接アクセスできることを
# 目的とした静的サイト配信専用サービスであり、IAM認証を必須とせず
# allUsersにroles/run.invokerを付与して公開する。
#
# 【注記】allUsersへのIAM権限付与には、プロジェクト（または組織）側の
# 組織ポリシー制約（constraints/iam.allowedPolicyMemberDomains）が
# ALLOW_ALLに設定されている必要がある。制約が組織のドメイン限定のままだと
# 本モジュールのapply（IAMバインディング作成）がFAILED_PRECONDITIONで失敗する。

resource "google_service_account" "frontend_run_sa" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "inuki (動作確認用フロント画面) 実行用サービスアカウント"
}

resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = var.service_name
  location = var.region

  # 静的サイト配信のみであり、設定変更での再作成が発生しても支障がないため
  # 削除保護は無効化する。
  deletion_protection = false

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.frontend_run_sa.email

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
    }
  }
}

# 誰でも（未認証で）アクセスできるようにallUsersにinvoker権限を付与する。
resource "google_cloud_run_v2_service_iam_member" "allow_unauthenticated" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

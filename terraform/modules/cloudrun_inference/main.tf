# cloudrun_inferenceモジュール
#
# design.md「コンポーネント2: 推論サービス (InferRun)」に基づき、
# Gemma 4 12B QATモデルをGPU(L4)上でホストするCloud Runサービスを作成する。
# Requirements 7.1: 「GCPのus-central1リージョンにおいて、GPUタイプL4を
# 割り当てたCloud Runサービスとして構築する」に対応する。
#
# 【注記】Cloud RunのGPUサポートはgoogle-betaプロバイダのリソース
# （`node_selector`によるGPUアクセラレータ指定、`gpu_zonal_redundancy_disabled`等）
# を必要とする場合があるため、本モジュールは`google-beta`プロバイダを使用する。

resource "google_service_account" "infer_run_sa" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "InferRun (推論サービス) 実行用サービスアカウント"
}

resource "google_cloud_run_v2_service" "inference" {
  provider = google-beta
  project  = var.project_id
  name     = var.service_name
  location = var.region

  # design.md Security Considerations:
  # 「APIRunからInferRunへの呼び出しはCloud RunのIAM認証を用い、
  #  InferRunはallUsersに公開しない」
  # -> 内部トラフィック（VPC内/Cloud Run間）のみを許可し、外部公開しない。
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  launch_stage = "BETA"

  template {
    service_account = google_service_account.infer_run_sa.email

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    # GPUを使用する場合、リクエストの同時実行数を1に制限することが
    # Cloud Run GPUのベストプラクティスとして推奨されている。
    max_instance_request_concurrency = 1

    node_selector {
      accelerator = var.gpu_type
    }

    # GPUゾーン冗長性（複数ゾーンにGPUインスタンスを分散配置する機能）は、
    # 既定で有効だが、有効にするには専用の higher GPU quota が必要となる
    # （プロジェクトによっては未割り当てで`400 You do not have quota for
    # using GPUs with zonal redundancy`エラーになる）。開発環境では
    # ゾーン冗長性を無効化し、通常のGPU quotaのみで動作するようにする。
    # 本番運用で高可用性が必要な場合は、GCPサポートにゾーン冗長GPU quotaの
    # 追加を申請した上でこの設定をtrueから変更（=falseへ）すること。
    gpu_zonal_redundancy_disabled = var.gpu_zonal_redundancy_disabled

    containers {
      image = var.image

      resources {
        limits = {
          cpu              = var.cpu
          memory           = var.memory
          "nvidia.com/gpu" = tostring(var.gpu_count)
        }
        # GPUを使い切るためインスタンスを常に起動状態で確保する
        cpu_idle = false
      }
    }
  }
}

# APIRunの実行用サービスアカウントにのみ、InferRunへの呼び出し権限を付与する
# （外部からの直接アクセスは`ingress = INGRESS_TRAFFIC_INTERNAL_ONLY`により拒否される）
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.inference.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.invoker_service_account_email}"
}

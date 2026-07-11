# cloudrun_inferenceモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Runサービスを作成するリージョン。GPU(L4)がサポートされるus-central1を指定すること"
  type        = string
}

variable "service_name" {
  description = "推論サービス（InferRun）のCloud Runサービス名"
  type        = string
}

variable "service_account_id" {
  description = <<-EOT
    InferRun実行用サービスアカウントのaccount_id。
    GCPの制約でaccount_idは6〜30文字である必要があるため、
    `service_name`（環境サフィックス込みで30文字を超える場合がある）とは
    別に、短い専用の値をルート構成側から渡す。
  EOT
  type        = string
}

variable "image" {
  description = "推論サービス（Gemma 4 12B QAT）のコンテナイメージURL"
  type        = string
}

variable "vpc_connector_id" {
  description = "VPCアクセスコネクタのID（必要に応じてモデル重みの取得元等への接続に使用）"
  type        = string
}

variable "invoker_service_account_email" {
  description = "InferRunの呼び出しを許可するサービスアカウント（APIRunの実行用サービスアカウント）のメールアドレス"
  type        = string
}

variable "gpu_type" {
  description = "割り当てるGPUのアクセラレータタイプ"
  type        = string
  default     = "nvidia-l4"
}

variable "gpu_count" {
  description = "割り当てるGPU数"
  type        = number
  default     = 1
}

variable "min_instance_count" {
  description = <<-EOT
    最小インスタンス数。design.md Performance Considerationsに記載の通り、
    GPUモデルのコールドスタート時間を避けるため1以上を設定することを推奨する。
  EOT
  type        = number
  default     = 1
}

variable "max_instance_count" {
  description = "最大インスタンス数"
  type        = number
  default     = 3
}

variable "cpu" {
  description = "コンテナに割り当てるCPU数（GPU使用時はCloud Runの要件上4以上等の制約がある場合がある。実行環境で確認すること）"
  type        = string
  default     = "4"
}

variable "memory" {
  description = "コンテナに割り当てるメモリ量"
  type        = string
  default     = "16Gi"
}

variable "gpu_zonal_redundancy_disabled" {
  description = <<-EOT
    GPUゾーン冗長性を無効化するかどうか。ゾーン冗長性の有効化には専用の
    GPU quota申請が必要なため、デフォルトはtrue（無効化）とする。
    quotaを確保済みで高可用性を重視する本番環境ではfalseに変更すること。
  EOT
  type        = bool
  default     = true
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

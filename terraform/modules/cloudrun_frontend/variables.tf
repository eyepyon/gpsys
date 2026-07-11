# cloudrun_frontendモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Runサービスを作成するリージョン"
  type        = string
}

variable "service_name" {
  description = "動作確認用フロント画面（inuki）のCloud Runサービス名"
  type        = string
}

variable "service_account_id" {
  description = "inuki実行用サービスアカウントのaccount_id（6〜30文字）"
  type        = string
}

variable "image" {
  description = "inuki（静的サイト配信用nginxコンテナ）のコンテナイメージURL"
  type        = string
}

variable "min_instance_count" {
  description = "最小インスタンス数"
  type        = number
  default     = 0
}

variable "max_instance_count" {
  description = "最大インスタンス数"
  type        = number
  default     = 3
}

variable "cpu" {
  description = "コンテナに割り当てるCPU数"
  type        = string
  default     = "1"
}

variable "memory" {
  description = <<-EOT
    コンテナに割り当てるメモリ量。GCPの制約上、CPU always allocated
    （本モジュールのデフォルト設定、cpu_idle未指定=false相当）の場合は
    512Mi未満を指定できない（"Total memory < 512 Mi is not supported with
    cpu always allocated"エラーになる）ため、512Mi以上を指定すること。
  EOT
  type        = string
  default     = "512Mi"
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

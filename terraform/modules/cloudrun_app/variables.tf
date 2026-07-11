# cloudrun_appモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Runサービスを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "service_name" {
  description = "アプリ本体サービス（APIRun）のCloud Runサービス名"
  type        = string
}

variable "service_account_email" {
  description = <<-EOT
    APIRunの実行用サービスアカウントのメールアドレス。
    InferRun（cloudrun_inferenceモジュール）がこのサービスアカウントに対して
    invoker権限を付与する必要があるため、モジュール間の循環参照を避けるべく
    サービスアカウント自体はルート構成（main.tf）で作成し、本変数経由で受け取る。
  EOT
  type        = string
}

variable "image" {
  description = "アプリ本体サービス（APIRun）のコンテナイメージURL"
  type        = string
}

variable "vpc_connector_id" {
  description = "Cloud SQLへのプライベート接続に使用するVPCアクセスコネクタのID"
  type        = string
}

variable "db_connection_secret_id" {
  description = "DB接続情報を格納したSecret ManagerシークレットのID（環境変数経由でマウントする）"
  type        = string
}

variable "inference_service_url" {
  description = "推論サービス（InferRun）の内部URL。APIRunからInferRunを呼び出す際の宛先として環境変数に渡す"
  type        = string
}

variable "storage_bucket_name" {
  description = "地域資源ファイル保存用Cloud Storageバケット名"
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
  default     = 10
}

variable "cpu" {
  description = "コンテナに割り当てるCPU数"
  type        = string
  default     = "1"
}

variable "memory" {
  description = "コンテナに割り当てるメモリ量"
  type        = string
  default     = "512Mi"
}

variable "allow_unauthenticated" {
  description = <<-EOT
    真の場合、APIRunへの未認証（allUsers）アクセスを許可する。
    利用者/自治体職員が直接HTTPSでアクセスするパブリックAPIとして運用する場合はtrueにするが、
    その場合はアプリ本体サービス側で別途の認証・認可（利用者ログイン等）を実装することを強く推奨する。
    falseの場合はIAM invoker権限を持つ主体のみがアクセス可能となる（デフォルトで安全側）。
  EOT
  type        = bool
  default     = false
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

# cloudrun_jobs_vacant_property_syncモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Run Jobsを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "job_name" {
  description = "居抜き物件同期サービス（VacantPropertySyncService）のCloud Run Jobs名"
  type        = string
}

variable "image" {
  description = "居抜き物件同期サービスのコンテナイメージURL"
  type        = string
}

variable "vpc_connector_id" {
  description = "Cloud SQLへのプライベート接続に使用するVPCアクセスコネクタのID"
  type        = string
}

variable "db_connection_secret_id" {
  description = "DB接続情報を格納したSecret ManagerシークレットのID"
  type        = string
}

variable "places_api_key" {
  description = "Google Maps Platform Places APIキー。Secret Managerへの登録用の入力値としてのみ使用する"
  type        = string
  sensitive   = true
}

variable "places_api_enabled" {
  description = "Google Places API呼び出しを許可するか"
  type        = bool
  default     = false
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

variable "max_retries" {
  description = "ジョブ実行失敗時の最大リトライ回数"
  type        = number
  default     = 1
}

variable "task_timeout" {
  description = "タスクのタイムアウト（秒単位の文字列、例: \"1800s\"）"
  type        = string
  default     = "1800s"
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

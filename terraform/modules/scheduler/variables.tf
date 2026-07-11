# schedulerモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Schedulerジョブを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "scheduler_job_name" {
  description = "Cloud Schedulerジョブ名"
  type        = string
  default     = "vacant-property-sync-trigger"
}

variable "schedule" {
  description = "実行スケジュール（unix-cron形式）"
  type        = string
}

variable "time_zone" {
  description = "スケジュール解釈に用いるタイムゾーン"
  type        = string
}

variable "target_job_name" {
  description = "トリガー対象のCloud Run Jobs名（居抜き物件同期サービス）"
  type        = string
}

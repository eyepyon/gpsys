# storageモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud Storageバケットを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "bucket_name" {
  description = "地域資源ファイル保存用バケット名（グローバルに一意である必要がある）"
  type        = string
}

variable "storage_class" {
  description = "バケットのストレージクラス"
  type        = string
  default     = "STANDARD"
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

# artifact_registryモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Artifact Registryリポジトリを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "repository_id" {
  description = "Artifact Registryリポジトリ名"
  type        = string
  default     = "regional-revitalization"
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

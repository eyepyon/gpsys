# cloudsqlモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "Cloud SQLインスタンスを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "instance_name" {
  description = "Cloud SQL for PostgreSQLインスタンス名"
  type        = string
}

variable "database_version" {
  description = "PostgreSQLのバージョン。PostGIS/pgvector/google_ml_integration拡張が利用可能なバージョンを指定する"
  type        = string
  default     = "POSTGRES_15"
}

variable "tier" {
  description = "Cloud SQLインスタンスのマシンタイプ（tier）"
  type        = string
}

variable "db_name" {
  description = "アプリケーション用データベース名"
  type        = string
}

variable "db_user" {
  description = "アプリケーション用DBユーザー名"
  type        = string
}

variable "db_password" {
  description = "アプリケーション用DBユーザーのパスワード（Secret Manager登録用の入力値）"
  type        = string
  sensitive   = true
}

variable "network_self_link" {
  description = "プライベートIP接続に使用するVPCネットワークのself_link"
  type        = string
}

variable "private_vpc_connection" {
  description = "Private Services Access用ピアリング接続への参照。Cloud SQL作成前にピアリングが確立していることを保証するためのdepends_on用"
  type        = any
}

variable "availability_type" {
  description = "Cloud SQLインスタンスの可用性タイプ（ZONAL または REGIONAL）"
  type        = string
  default     = "ZONAL"
}

variable "labels" {
  description = "リソースに付与する共通ラベル"
  type        = map(string)
  default     = {}
}

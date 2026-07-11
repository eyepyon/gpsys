# ルート構成の入力変数定義。
#
# 機密性の高い値（DBパスワード、Places APIキー等）は `sensitive = true` を
# 付与し、Terraformの実行ログや`plan`/`apply`の出力に平文表示されないようにする。
# ただし `sensitive = true` は出力の抑制のみを行うものであり、状態ファイル
# (tfstate)自体への格納を防ぐものではない。そのため実際の値は
# Secret Manager側で管理し、Terraformには「Secret Managerに登録する初期値」
# としてのみ一時的に受け渡す設計とする（詳細はREADME.md参照）。

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "全リソースを作成するGCPリージョン（本システムはus-central1に固定運用する）"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "環境識別子（例: dev, staging, prod）。リソース名のサフィックスに使用する"
  type        = string
  default     = "dev"
}

variable "app_service_name" {
  description = "アプリ本体サービス（APIRun）のCloud Runサービス名"
  type        = string
  default     = "regional-revitalization-api"
}

variable "app_image" {
  description = "アプリ本体サービス（APIRun）のコンテナイメージURL（Artifact Registry等）"
  type        = string
}

variable "inference_service_name" {
  description = "推論サービス（InferRun）のCloud Runサービス名"
  type        = string
  default     = "regional-revitalization-infer"
}

variable "inference_image" {
  description = "推論サービス（InferRun、Gemma 4 12B QAT）のコンテナイメージURL"
  type        = string
}

variable "vacant_sync_job_name" {
  description = "居抜き物件同期サービス（VacantPropertySyncService）のCloud Run Jobs名"
  type        = string
  default     = "vacant-property-sync"
}

variable "vacant_sync_image" {
  description = "居抜き物件同期サービス（Cloud Run Jobs）のコンテナイメージURL"
  type        = string
}

variable "vpc_network_name" {
  description = "VPCコネクタを作成する対象VPCネットワーク名"
  type        = string
  default     = "default"
}

variable "vpc_connector_cidr" {
  description = "VPCアクセスコネクタに割り当てるCIDR範囲（/28を指定すること）"
  type        = string
  default     = "10.8.0.0/28"
}

variable "db_instance_name" {
  description = "Cloud SQL for PostgreSQLインスタンス名"
  type        = string
  default     = "regional-revitalization-db"
}

variable "db_tier" {
  description = "Cloud SQLインスタンスのマシンタイプ（tier）"
  type        = string
  default     = "db-custom-2-8192"
}

variable "db_name" {
  description = "アプリケーション用データベース名"
  type        = string
  default     = "regional_revitalization"
}

variable "db_user" {
  description = "アプリケーション用DBユーザー名"
  type        = string
  default     = "app_user"
}

variable "db_password" {
  description = "アプリケーション用DBユーザーのパスワード。値はSecret Manager登録用の一時的な入力としてのみ使用し、実運用ではCI/CD等のシークレットストアから注入すること"
  type        = string
  sensitive   = true
}

variable "storage_bucket_name" {
  description = "地域資源ファイル保存用Cloud Storageバケット名（グローバルに一意である必要がある）"
  type        = string
}

variable "places_api_key" {
  description = "Google Maps Platform Places APIキー。値はSecret Manager登録用の一時的な入力としてのみ使用する"
  type        = string
  sensitive   = true
}

variable "vacant_sync_schedule" {
  description = "居抜き物件同期サービスのCloud Schedulerによる実行スケジュール（unix-cron形式）"
  type        = string
  default     = "0 3 * * *" # 日次(毎日03:00 UTC)実行を既定とする
}

variable "vacant_sync_time_zone" {
  description = "Cloud Schedulerのスケジュール解釈に用いるタイムゾーン"
  type        = string
  default     = "Etc/UTC"
}

variable "labels" {
  description = "全リソースに付与する共通ラベル"
  type        = map(string)
  default = {
    "app" = "regional-revitalization"
  }
}

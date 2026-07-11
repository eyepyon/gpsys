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
  description = "推論サービス（InferRun、Gemma 4搭載）のCloud Runサービス名"
  type        = string
  default     = "inuki-gemma4"
}

variable "inference_image" {
  description = "推論サービス（InferRun、Gemma 4 12B QAT）のコンテナイメージURL"
  type        = string
}

variable "frontend_service_name" {
  description = "動作確認用フロント画面（inuki）のCloud Runサービス名"
  type        = string
  default     = "inuki"
}

variable "frontend_image" {
  description = "動作確認用フロント画面（inuki）のコンテナイメージURL（Artifact Registry等）"
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

variable "artifact_registry_repository_id" {
  description = "コンテナイメージを格納するArtifact Registryリポジトリ名"
  type        = string
  default     = "regional-revitalization"
}

variable "enable_github_actions_wif" {
  description = "GitHub Actions用のWorkload Identity連携（プール・プロバイダ・デプロイ用サービスアカウント）を作成するかどうか。初回はfalseで適用し、人間の管理者権限で作成した後にtrueへ切り替える運用を想定する"
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "GitHub ActionsからのWIF認証を許可するGitHubリポジトリ（\"org-name/repo-name\"形式）。enable_github_actions_wif=trueの場合に使用する"
  type        = string
  default     = ""
}

variable "app_allow_unauthenticated" {
  description = <<-EOT
    真の場合、APIRun（アプリ本体サービス）への未認証（allUsers）アクセスを
    許可する。動作確認用フロント画面からのアクセスや、パブリックAPIとして
    運用する場合にtrueにする。デフォルトはfalse（IAM認証必須、安全側）。
  EOT
  type        = bool
  default     = false
}

variable "admin_places_api_key" {
  description = <<-EOT
    管理画面（/admin/）の「この場所でGoogle Places APIを検索する」機能で
    使用するPlaces APIキー。居抜き物件同期サービス（Cloud Run Jobs）の
    Places APIキーとはSecret Managerシークレットを分離し、APIRun実行用
    サービスアカウントにのみアクセス権限を付与する。値はSecret Manager
    登録用の一時的な入力としてのみ使用し、実運用ではCI/CD等のシークレット
    ストアから注入すること。空文字列の場合はこの機能を無効化する
    （モッククライアントのまま動作し、実際のPlaces API呼び出しは行わない）。
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "admin_initial_username" {
  description = <<-EOT
    管理画面(inuki/admin)の初回管理者アカウントのログインID。
    管理ユーザーが1件も存在しない状態でAPIRunが起動した際、この値と
    admin_initial_passwordを用いて自動的に初回アカウントが作成される。
    2件目以降の管理ユーザーは、管理画面のユーザー管理ページから作成する。
  EOT
  type        = string
  default     = "admin"
}

variable "admin_initial_password" {
  description = <<-EOT
    管理画面の初回管理者アカウントのパスワード（8文字以上）。値はSecret
    Manager登録用の一時的な入力としてのみ使用し、実運用ではCI/CD等の
    シークレットストアから注入すること。
  EOT
  type        = string
  sensitive   = true

  validation {
    # 空文字列のままapplyすると、Secret Manager APIが
    # 「Field [payload] is required」という分かりにくいエラーを返すため、
    # ここで早期に分かりやすいエラーメッセージを出す。
    # CI/CDのGitHub Secrets（ADMIN_INITIAL_PASSWORD）が未設定の場合に
    # 空文字列が渡されるケースを想定している。
    condition     = length(var.admin_initial_password) >= 8
    error_message = "admin_initial_passwordは8文字以上である必要があります。GitHub Secrets等でADMIN_INITIAL_PASSWORDが設定されているか確認してください。"
  }
}

variable "app_cors_allowed_origins" {
  description = <<-EOT
    ブラウザから直接APIRunを呼び出すことを許可するオリジンのカンマ区切り
    一覧（例: "https://storage.googleapis.com"）。動作確認用フロント画面等で
    使用する。空文字列（デフォルト）の場合はCORSを有効化しない。
  EOT
  type        = string
  default     = ""
}

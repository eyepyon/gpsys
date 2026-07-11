# storageモジュール入力変数
#
# 【注記】本モジュールはバケットを新規作成せず、Terraform管理外で事前作成
# された既存バケット（tfstateと共用）を参照するのみである（main.tf参照）。
# そのため`project_id`/`region`/`storage_class`/`labels`等、バケット作成に
# 必要だった変数は不要となった。

variable "bucket_name" {
  description = "地域資源ファイル保存用バケット名（tfstateと共用のバケット名、resources/プレフィックス配下を使用）"
  type        = string
}

variable "app_run_service_account_email" {
  description = "APIRun（アプリ本体サービス）実行用サービスアカウントのメールアドレス。resources/プレフィックス配下への限定アクセス権限の付与先として使用する"
  type        = string
}

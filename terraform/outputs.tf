# ルート構成の出力値

output "app_run_url" {
  description = "アプリ本体サービス（APIRun）のURL"
  value       = module.cloudrun_app.service_url
}

output "infer_run_url" {
  description = "推論サービス（InferRun）の内部URL"
  value       = module.cloudrun_inference.service_url
}

output "cloudsql_instance_connection_name" {
  description = "Cloud SQLインスタンスの接続名（project:region:instance形式）"
  value       = module.cloudsql.instance_connection_name
}

output "storage_bucket_name" {
  description = "地域資源ファイル保存用Cloud Storageバケット名"
  value       = module.storage.bucket_name
}

output "vacant_property_sync_job_name" {
  description = "居抜き物件同期サービスのCloud Run Jobs名"
  value       = module.vacant_property_sync.job_name
}

output "vacant_property_sync_scheduler_job_name" {
  description = "居抜き物件同期サービスをトリガーするCloud Schedulerジョブ名"
  value       = module.scheduler.scheduler_job_name
}

output "db_connection_secret_name" {
  description = "DB接続情報を格納したSecret Managerシークレットの完全なリソース名"
  value       = module.cloudsql.db_connection_secret_name
}

output "artifact_registry_repository_url" {
  description = "コンテナイメージのプッシュ/プル先となるArtifact RegistryリポジトリURL"
  value       = module.artifact_registry.repository_url
}

output "github_actions_workload_identity_provider" {
  description = "GitHub Actionsの`google-github-actions/auth`アクションに設定するWorkload Identityプロバイダの完全なリソース名（enable_github_actions_wif=trueの場合のみ値を持つ）"
  value       = var.enable_github_actions_wif ? module.github_actions_wif[0].workload_identity_provider : null
}

output "github_actions_deployer_service_account_email" {
  description = "GitHub Actionsがなりすます(impersonate)デプロイ用サービスアカウントのメールアドレス（enable_github_actions_wif=trueの場合のみ値を持つ）"
  value       = var.enable_github_actions_wif ? module.github_actions_wif[0].deployer_service_account_email : null
}

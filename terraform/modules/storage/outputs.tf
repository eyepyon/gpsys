# storageモジュール出力値

output "bucket_name" {
  description = "地域資源ファイル保存用Cloud Storageバケット名（tfstateと共用、resources/プレフィックス配下を使用）"
  value       = data.google_storage_bucket.resources.name
}

output "bucket_url" {
  description = "地域資源ファイル保存用Cloud Storageバケットの gs:// 形式URL"
  value       = data.google_storage_bucket.resources.url
}

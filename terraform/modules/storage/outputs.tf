# storageモジュール出力値

output "bucket_name" {
  description = "作成したCloud Storageバケット名"
  value       = google_storage_bucket.resources.name
}

output "bucket_url" {
  description = "作成したCloud Storageバケットの gs:// 形式URL"
  value       = google_storage_bucket.resources.url
}

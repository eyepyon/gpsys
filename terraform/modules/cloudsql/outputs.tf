# cloudsqlモジュール出力値

output "instance_name" {
  description = "作成したCloud SQLインスタンス名"
  value       = google_sql_database_instance.instance.name
}

output "instance_connection_name" {
  description = "Cloud SQL Auth Proxy等で使用する接続名（project:region:instance形式）"
  value       = google_sql_database_instance.instance.connection_name
}

output "private_ip_address" {
  description = "Cloud SQLインスタンスのプライベートIPアドレス"
  value       = google_sql_database_instance.instance.private_ip_address
}

output "db_connection_secret_id" {
  description = "DB接続情報を格納したSecret ManagerシークレットのID"
  value       = google_secret_manager_secret.db_connection.secret_id
}

output "db_connection_secret_name" {
  description = "DB接続情報を格納したSecret Managerシークレットの完全なリソース名"
  value       = google_secret_manager_secret.db_connection.name
}

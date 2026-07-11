# networkモジュール出力値

output "connector_id" {
  description = "作成したVPCアクセスコネクタのリソースID（Cloud Runの`vpc_access`から参照する）"
  value       = google_vpc_access_connector.connector.id
}

output "connector_name" {
  description = "作成したVPCアクセスコネクタの名前"
  value       = google_vpc_access_connector.connector.name
}

output "network_self_link" {
  description = "対象VPCネットワークのself_link（Cloud SQLのprivate_network設定等で参照する）"
  value       = data.google_compute_network.vpc.self_link
}

output "private_vpc_connection" {
  description = "Cloud SQL等がプライベートIPを利用可能になるまで待機するためのVPCピアリング接続への参照（depends_onで利用する）"
  value       = google_service_networking_connection.private_vpc_connection
}

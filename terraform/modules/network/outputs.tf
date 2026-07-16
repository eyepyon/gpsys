# networkモジュール出力値

output "network_self_link" {
  description = "対象VPCネットワークのself_link（Cloud SQLのprivate_network設定等で参照する）"
  value       = data.google_compute_network.vpc.self_link
}

output "private_vpc_connection" {
  description = "Cloud SQL等がプライベートIPを利用可能になるまで待機するためのVPCピアリング接続への参照（depends_onで利用する）"
  value       = google_service_networking_connection.private_vpc_connection
}

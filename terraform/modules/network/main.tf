# networkモジュール
#
# Cloud Run（アプリ本体サービス・推論サービス・居抜き物件同期Jobs）から
# Cloud SQL for PostgreSQLへプライベートIP経由で接続するためのVPCアクセス
# コネクタ（Serverless VPC Access）、およびCloud SQLのプライベートIPに
# 必要なPrivate Services Access（VPCピアリング）を作成する。
#
# design.md「コンポーネント6: IaC」「Security Considerations」の
# 「Cloud SQL接続: Cloud SQL Auth ProxyまたはプライベートIP + VPCコネクタ経由で
# 接続し、パブリックIPを無効化する」という方針に対応する。

data "google_compute_network" "vpc" {
  project = var.project_id
  name    = var.network_name
}

# Cloud SQLのプライベートIP接続に必要なIPレンジ（Private Services Access用）
resource "google_compute_global_address" "private_ip_range" {
  project       = var.project_id
  name          = "${var.connector_name}-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = data.google_compute_network.vpc.id
}

# VPCとGoogleサービス（Cloud SQL等）間のプライベートサービスアクセス用ピアリング
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = data.google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

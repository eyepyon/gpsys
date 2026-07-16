# networkモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "network_name" {
  description = "Cloud SQLプライベート接続に使用するVPCネットワーク名"
  type        = string
}

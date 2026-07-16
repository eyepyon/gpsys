# networkモジュール入力変数

variable "project_id" {
  description = "GCPプロジェクトID"
  type        = string
}

variable "region" {
  description = "VPCコネクタを作成するリージョン（us-central1固定運用）"
  type        = string
}

variable "network_name" {
  description = "VPCアクセスコネクタを紐づける対象VPCネットワーク名"
  type        = string
}

variable "connector_name" {
  description = "VPCアクセスコネクタの名前"
  type        = string
  default     = "regional-revit-connector"
}

variable "ip_cidr_range" {
  description = "VPCアクセスコネクタに割り当てるCIDR範囲（/28であること）"
  type        = string
}

variable "min_instances" {
  description = "VPCアクセスコネクタの最小インスタンス数"
  type        = number
  default     = 2
}

variable "max_instances" {
  description = "VPCアクセスコネクタの最大インスタンス数"
  type        = number
  default     = 2
}

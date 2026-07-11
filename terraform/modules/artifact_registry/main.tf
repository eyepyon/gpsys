# artifact_registryモジュール
#
# GitHub Actionsからビルドしたコンテナイメージ（APIRun/InferRun/居抜き物件同期サービス）を
# 格納するAritifact Registry（Dockerリポジトリ）を作成する。
# `terraform.tfvars.example`の`app_image`等が参照するリポジトリパス
# （us-central1-docker.pkg.dev/PROJECT_ID/regional-revitalization/...）に対応する。

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "地方創生支援システム（APIRun/InferRun/居抜き物件同期サービス）のコンテナイメージ格納用リポジトリ"
  format        = "DOCKER"

  labels = var.labels
}

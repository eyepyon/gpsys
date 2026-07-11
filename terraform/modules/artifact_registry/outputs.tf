# artifact_registryモジュール出力値

output "repository_id" {
  description = "作成したArtifact Registryリポジトリ名"
  value       = google_artifact_registry_repository.containers.repository_id
}

output "repository_url" {
  description = "コンテナイメージのプッシュ/プル先となるリポジトリURL（<region>-docker.pkg.dev/<project>/<repository_id>）"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"
}

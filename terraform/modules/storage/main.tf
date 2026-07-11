# storageモジュール
#
# design.md「コンポーネント4: ファイルストレージ (Cloud Storage)」および
# Requirements 9.1に基づき、地域資源に紐づくファイル（画像・PDF等）の
# 保存先バケットを参照する。
#
# 【バケット統合に関する重要な設計判断】
# 本システムは、Terraformのtfstate保存先バケットと、地域資源ファイルの
# 保存先バケットを1つのGCSバケットに統合し、プレフィックス（フォルダ相当）
# で用途を分離する運用とする。
#   - `terraform/state/` プレフィックス: tfstate（`versions.tf`の
#     `backend "gcs" { prefix = "terraform/state" }`）
#   - `resources/` プレフィックス: 地域資源ファイル（`registration.py`が
#     `resources/{uuid}`という名前でオブジェクトを配置する）
#
# tfstate用バケットは「バケット自体をTerraformで管理すると、初回init時に
# バケットが存在しない循環依存が発生する」ため、Terraform管理外で事前に
# 作成する必要がある（詳細はdocs/deployment-guide.mdの初回セットアップ手順を
# 参照）。バケットを統合した結果、地域資源ファイル用バケットも同様に
# Terraform管理外で事前作成されたものを参照する形になるため、本モジュールは
# バケットを新規作成せず、既存バケットを`data`ソースとして参照するのみとする。
#
# 非公開バケットの要件（事前作成時に`gcloud storage buckets create`で設定する。
# 詳細はdocs/deployment-guide.md参照）:
# - `--uniform-bucket-level-access` によりオブジェクト単位のACLを禁止し、
#   バケットレベルのIAMのみでアクセス制御を統一する
# - `allUsers`/`allAuthenticatedUsers`への権限付与を行わない（公開アクセスを許可しない）
# - 外部への提供は署名付きURL（有効期限付き）のみで行う（アプリ側の責務）
# - `--public-access-prevention=enforced` を設定する

data "google_storage_bucket" "resources" {
  name = var.bucket_name
}

# 【セキュリティ上の重要な注記】バケットをtfstateと共用するため、
# APIRun実行用サービスアカウントには、バケット全体への権限ではなく
# IAM条件（Condition）により`resources/`プレフィックス配下のオブジェクトに
# 限定した権限のみを付与する。これにより、APIRunの実行用サービスアカウントが
# 機密値を含むtfstate（`terraform/state/`プレフィックス配下）へ
# アクセスできないようにする。
resource "google_storage_bucket_iam_member" "app_run_resources_access" {
  bucket = data.google_storage_bucket.resources.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_run_service_account_email}"

  condition {
    title       = "resources-prefix-only"
    description = "地域資源ファイル用プレフィックス（resources/）配下のオブジェクトのみアクセスを許可する"
    expression  = "resource.name.startsWith(\"projects/_/buckets/${data.google_storage_bucket.resources.name}/objects/resources/\")"
  }
}

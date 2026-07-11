# storageモジュール
#
# design.md「コンポーネント4: ファイルストレージ (Cloud Storage)」および
# Requirements 9.1に基づき、地域資源に紐づくファイル（画像・PDF等）を
# 保存するための非公開Cloud Storageバケットを作成する。
#
# 非公開バケットの要件:
# - `uniform_bucket_level_access = true` によりオブジェクト単位のACLを禁止し、
#   バケットレベルのIAMのみでアクセス制御を統一する
# - `google_storage_bucket_iam_member`で`allUsers`/`allAuthenticatedUsers`への
#   権限付与を行わない（公開アクセスを許可しない）
# - 外部への提供は署名付きURL（有効期限付き）のみで行う（アプリ側の責務）
# - パブリックアクセス防止（`public_access_prevention`）を強制する

resource "google_storage_bucket" "resources" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = var.storage_class
  uniform_bucket_level_access = true

  # バケットIAMポリシーによる意図しない公開設定も含めて禁止する
  public_access_prevention = "enforced"

  versioning {
    enabled = true
  }

  labels = var.labels
}

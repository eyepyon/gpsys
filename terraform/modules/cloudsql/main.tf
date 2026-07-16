# cloudsqlモジュール
#
# design.md「コンポーネント3: データストア (Cloud SQL for PostgreSQL)」に基づき、
# PostGIS拡張・pgvector拡張・google_ml_integration拡張を利用可能な
# Cloud SQL for PostgreSQLインスタンスを作成する。
#
# 【拡張機能の有効化について】
# PostGIS拡張・pgvector拡張（`CREATE EXTENSION IF NOT EXISTS postgis;` /
# `CREATE EXTENSION IF NOT EXISTS vector;`）自体はデータベース内のSQL文
# （マイグレーションスクリプト、`migrations/001_init_schema.sql`等）で有効化する。
# Terraformの責務は、それらの拡張が有効化可能な状態（インスタンスフラグ、
# IAM権限）を用意することである。
#
# `google_ml_integration`拡張は、インスタンスフラグ
# `cloudsql.enable_google_ml_integration = on` の設定に加え、
# インスタンスのサービスアカウントにVertex AI呼び出し権限（`roles/aiplatform.user`）
# が必要となるため、本モジュールで設定する。

resource "google_sql_database_instance" "instance" {
  project             = var.project_id
  name                = var.instance_name
  region              = var.region
  database_version    = var.database_version
  deletion_protection = true

  # Private Services Access（VPCピアリング）が確立してからインスタンスを作成する
  depends_on = [var.private_vpc_connection]

  settings {
    tier              = var.tier
    availability_type = var.availability_type

    ip_configuration {
      # パブリックIPを無効化し、VPC経由のプライベートIP接続のみを許可する
      # （design.md Security Considerations: 「Cloud SQL Auth Proxyまたは
      # プライベートIP + VPCコネクタ経由で接続し、パブリックIPを無効化する」）
      ipv4_enabled    = false
      private_network = var.network_self_link
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false
    }

    # google_ml_integration拡張（DB側embedding生成）を有効化するためのフラグ。
    # PostGIS/pgvector拡張はCREATE EXTENSION文（マイグレーション側）で有効化するため
    # インスタンスフラグは不要。
    database_flags {
      name  = "cloudsql.enable_google_ml_integration"
      value = "on"
    }

    user_labels = var.labels
  }
}

resource "google_sql_database" "app_db" {
  project  = var.project_id
  name     = var.db_name
  instance = google_sql_database_instance.instance.name
}

resource "google_sql_user" "app_user" {
  project  = var.project_id
  name     = var.db_user
  instance = google_sql_database_instance.instance.name
  password = var.db_password
}

# google_ml_integration拡張がSQL関数呼び出しからVertex AIの埋め込みモデルを
# 呼び出すために必要な権限。Cloud SQLインスタンスのサービスアカウントに付与する。
resource "google_project_iam_member" "sql_vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_sql_database_instance.instance.service_account_email_address}"
}

# --- Secret Manager: DB接続情報 ---
#
# design.md Security Considerations「認証情報管理: DB接続情報等のシークレットは
# Secret Managerで管理し、Terraformの状態ファイルに平文で残さない」に対応する。
#
# 【tfstateに関する注記】`sensitive = true`はCLI出力・plan差分表示を抑制するが、
# 値自体はリソースの属性としてtfstateファイルに保存される点はTerraformの一般的な
# 制約である。これを踏まえ、本番運用では以下のいずれか（またはその組み合わせ）を
# 推奨する:
#   1) リモートバックエンド（GCS等）を暗号化・アクセス制御されたバケットに設定する
#   2) 初回作成後はSecret Manager側でシークレットの値をローテーションし、
#      Terraform管理外の経路（`gcloud secrets versions add`等）で更新する
#   3) `db_password`変数はCI/CDのシークレットストアから注入し、リポジトリや
#      ローカルの`terraform.tfvars`に平文を書かない
resource "google_secret_manager_secret" "db_connection" {
  project   = var.project_id
  secret_id = "${var.instance_name}-db-connection"

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_version" "db_connection" {
  secret = google_secret_manager_secret.db_connection.id

  # DB接続情報をJSON形式でまとめて1つのシークレットバージョンとして格納する。
  # アプリ本体サービスは起動時にこのシークレットを読み取り、接続文字列を組み立てる。
  secret_data = jsonencode({
    host     = google_sql_database_instance.instance.private_ip_address
    port     = 5432
    database = google_sql_database.app_db.name
    user     = google_sql_user.app_user.name
    password = var.db_password
  })
}

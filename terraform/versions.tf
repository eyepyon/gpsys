# Terraformおよびプロバイダのバージョン制約を定義する。
#
# 【重要な注記】本コードは、Terraform CLIが利用できない開発環境で作成された。
# そのため `terraform init` / `validate` / `plan` / `apply` による実行検証は
# 本フェーズでは実施していない。実際の検証はTerraform CLIが利用可能な別環境で
# 実施すること（詳細は terraform/README.md を参照）。

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # 本番運用時はTerraformの状態ファイルをGCSバケット等のリモートバックエンドに
  # 保存することを強く推奨する（ローカルのtfstateには機密値の断片が残るため）。
  # 例:
  # backend "gcs" {
  #   bucket = "regional-revitalization-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Cloud Run のGPU割り当て等、一部の機能はベータ機能として
# google-beta プロバイダ経由で提供される場合があるため併せて定義する。
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

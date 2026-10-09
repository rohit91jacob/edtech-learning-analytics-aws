# Glue Data Catalog databases (the Iceberg catalog for Spark and the schemas dbt builds on
# Athena) and an Athena workgroup with enforced, encrypted results and a per-query scan cap.

locals {
  prefix = "${var.project}_${var.environment}"
  # silver: written by EMR Serverless. The rest: dbt schemas (generate_schema_name prefixes them).
  databases = ["silver", "staging", "intermediate", "marts", "reference"]
}

resource "aws_glue_catalog_database" "this" {
  for_each     = toset(local.databases)
  name         = "${local.prefix}_${each.key}"
  description  = "OULAD learning analytics: ${each.key} layer"
  location_uri = "s3://${var.lake_bucket}/warehouse/${local.prefix}_${each.key}.db"
}

resource "aws_athena_workgroup" "this" {
  name          = "${var.project}-${var.environment}"
  description   = "dbt and ad-hoc queries over the OULAD marts"
  force_destroy = var.force_destroy
  state         = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_per_query
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
    result_configuration {
      output_location = "s3://${var.athena_results_bucket}/results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = var.kms_key_arn
      }
    }
  }
}

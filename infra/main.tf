# OULAD learning analytics on AWS: S3 -> EMR Serverless (PySpark) -> Iceberg on Glue -> dbt on
# Athena, orchestrated by Step Functions. Validated in CI (fmt, validate, tflint, checkov); not
# deployed by this repository. See docs/runbook.md#deploying-to-aws before applying.

module "storage" {
  source        = "./modules/storage"
  project       = var.project
  environment   = var.environment
  force_destroy = var.force_destroy
}

module "catalog" {
  source                         = "./modules/catalog"
  project                        = var.project
  environment                    = var.environment
  lake_bucket                    = module.storage.lake_bucket
  athena_results_bucket          = module.storage.athena_results_bucket
  kms_key_arn                    = module.storage.kms_key_arn
  bytes_scanned_cutoff_per_query = var.athena_bytes_scanned_cutoff
  force_destroy                  = var.force_destroy
}

module "emr" {
  source          = "./modules/emr_serverless"
  project         = var.project
  environment     = var.environment
  release_label   = var.emr_release_label
  max_cpu         = var.emr_max_cpu
  max_memory      = var.emr_max_memory
  lake_bucket     = module.storage.lake_bucket
  lake_bucket_arn = module.storage.lake_bucket_arn
  raw_bucket_arn  = module.storage.raw_bucket_arn
  code_bucket_arn = module.storage.code_bucket_arn
  silver_database = module.catalog.database_names["silver"]
  kms_key_arn     = module.storage.kms_key_arn
}

module "orchestration" {
  source                    = "./modules/orchestration"
  project                   = var.project
  environment               = var.environment
  definition_path           = "${path.root}/../src/edtech_analytics/orchestration/pipeline.asl.json"
  emr_application_id        = module.emr.application_id
  emr_application_arn       = module.emr.application_arn
  emr_job_role_arn          = module.emr.job_role_arn
  raw_bucket                = module.storage.raw_bucket
  lake_bucket               = module.storage.lake_bucket
  lake_bucket_arn           = module.storage.lake_bucket_arn
  code_bucket               = module.storage.code_bucket
  code_bucket_arn           = module.storage.code_bucket_arn
  athena_results_bucket     = module.storage.athena_results_bucket
  athena_results_bucket_arn = module.storage.athena_results_bucket_arn
  athena_workgroup_name     = module.catalog.workgroup_name
  athena_workgroup_arn      = module.catalog.workgroup_arn
  glue_database_names       = module.catalog.database_names
  kms_key_arn               = module.storage.kms_key_arn
  notification_emails       = var.notification_emails
  log_retention_days        = var.log_retention_days
  enable_schedule           = var.enable_schedule
}

module "guardrails" {
  source             = "./modules/guardrails"
  project            = var.project
  environment        = var.environment
  monthly_budget_usd = var.monthly_budget_usd
  alert_emails       = var.notification_emails
  sns_topic_arn      = module.orchestration.sns_topic_arn
}

module "github_oidc" {
  count                      = var.enable_github_oidc ? 1 : 0
  source                     = "./modules/github_oidc"
  project                    = var.project
  environment                = var.environment
  github_repository          = var.github_repository
  create_oidc_provider       = var.create_github_oidc_provider
  existing_oidc_provider_arn = var.existing_github_oidc_provider_arn
  code_bucket_arn            = module.storage.code_bucket_arn
  raw_bucket_arn             = module.storage.raw_bucket_arn
  state_machine_arn          = module.orchestration.state_machine_arn
  kms_key_arn                = module.storage.kms_key_arn
}

output "raw_bucket" {
  description = "Target for `edtech land-s3 --bucket`."
  value       = module.storage.raw_bucket
}

output "lake_bucket" {
  description = "Iceberg warehouse bucket."
  value       = module.storage.lake_bucket
}

output "code_bucket" {
  description = "Upload dist/emr/* to s3://<code_bucket>/jobs/ and the dbt zip to dbt/."
  value       = module.storage.code_bucket
}

output "glue_databases" {
  description = "Glue database per layer."
  value       = module.catalog.database_names
}

output "athena_workgroup" {
  description = "Athena workgroup for dbt and queries."
  value       = module.catalog.workgroup_name
}

output "emr_application_id" {
  description = "EMR Serverless application id."
  value       = module.emr.application_id
}

output "state_machine_arn" {
  description = "Pipeline state machine."
  value       = module.orchestration.state_machine_arn
}

output "deploy_role_arn" {
  description = "GitHub OIDC deploy role (set as the AWS_DEPLOY_ROLE_ARN repository variable)."
  value       = try(module.github_oidc[0].deploy_role_arn, null)
}

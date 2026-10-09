output "kms_key_arn" {
  description = "ARN of the project data key."
  value       = aws_kms_key.data.arn
}

output "raw_bucket" {
  description = "Raw zone bucket (OULAD archive files, content-addressed)."
  value       = module.raw.id
}

output "raw_bucket_arn" {
  description = "Raw bucket ARN."
  value       = module.raw.arn
}

output "lake_bucket" {
  description = "Iceberg warehouse bucket."
  value       = module.lake.id
}

output "lake_bucket_arn" {
  description = "Lake bucket ARN."
  value       = module.lake.arn
}

output "code_bucket" {
  description = "Job artefacts (EMR entry point, py-files zip, dbt project)."
  value       = module.code.id
}

output "code_bucket_arn" {
  description = "Code bucket ARN."
  value       = module.code.arn
}

output "athena_results_bucket" {
  description = "Athena query results."
  value       = module.athena_results.id
}

output "athena_results_bucket_arn" {
  description = "Athena results bucket ARN."
  value       = module.athena_results.arn
}

output "logs_bucket" {
  description = "S3 access-log sink."
  value       = aws_s3_bucket.logs.id
}

output "logs_bucket_arn" {
  description = "Access-log bucket ARN."
  value       = aws_s3_bucket.logs.arn
}

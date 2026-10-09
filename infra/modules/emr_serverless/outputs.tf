output "application_id" {
  description = "EMR Serverless application id."
  value       = aws_emrserverless_application.spark.id
}

output "application_arn" {
  description = "EMR Serverless application ARN."
  value       = aws_emrserverless_application.spark.arn
}

output "job_role_arn" {
  description = "Execution role passed to every job run."
  value       = aws_iam_role.job.arn
}

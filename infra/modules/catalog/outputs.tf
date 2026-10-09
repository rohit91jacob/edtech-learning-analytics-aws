output "database_names" {
  description = "Glue database name per layer."
  value       = { for k, db in aws_glue_catalog_database.this : k => db.name }
}

output "database_arns" {
  description = "Glue database ARNs."
  value       = [for db in aws_glue_catalog_database.this : db.arn]
}

output "workgroup_name" {
  description = "Athena workgroup."
  value       = aws_athena_workgroup.this.name
}

output "workgroup_arn" {
  description = "Athena workgroup ARN."
  value       = aws_athena_workgroup.this.arn
}

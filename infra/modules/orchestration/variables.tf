variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "definition_path" {
  description = "Path to the shared ASL template (pipeline.asl.json)."
  type        = string
}

variable "emr_application_id" {
  description = "EMR Serverless application id."
  type        = string
}

variable "emr_application_arn" {
  description = "EMR Serverless application ARN."
  type        = string
}

variable "emr_job_role_arn" {
  description = "EMR Serverless job execution role."
  type        = string
}

variable "raw_bucket" {
  description = "Raw bucket name."
  type        = string
}

variable "lake_bucket" {
  description = "Lake bucket name."
  type        = string
}

variable "lake_bucket_arn" {
  description = "Lake bucket ARN."
  type        = string
}

variable "code_bucket" {
  description = "Code bucket name."
  type        = string
}

variable "code_bucket_arn" {
  description = "Code bucket ARN."
  type        = string
}

variable "athena_results_bucket" {
  description = "Athena results bucket name."
  type        = string
}

variable "athena_results_bucket_arn" {
  description = "Athena results bucket ARN."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup dbt runs in."
  type        = string
}

variable "athena_workgroup_arn" {
  description = "Athena workgroup ARN."
  type        = string
}

variable "glue_database_names" {
  description = "Glue database per layer (silver, staging, intermediate, marts, reference)."
  type        = map(string)
}

variable "kms_key_arn" {
  description = "Project data key."
  type        = string
}

variable "notification_emails" {
  description = "Email addresses subscribed to pipeline notifications (confirmation required)."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 365
}

variable "enable_schedule" {
  description = "Turn the weekly schedule on (off by default; the dataset is static)."
  type        = bool
  default     = false
}

variable "schedule_expression" {
  description = "EventBridge Scheduler expression for the pipeline."
  type        = string
  default     = "cron(0 6 ? * MON *)"
}

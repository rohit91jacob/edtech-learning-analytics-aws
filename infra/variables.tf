variable "aws_region" {
  description = "AWS region (London by default; the data comes from a UK university)."
  type        = string
  default     = "eu-west-2"
}

variable "project" {
  description = "Project slug: resource-name prefix and the value of the project cost-allocation tag."
  type        = string
  default     = "edtech"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.project))
    error_message = "Use 3-16 lowercase letters/digits (it is used in bucket and Glue database names)."
  }
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "owner" {
  description = "Owner tag."
  type        = string
  default     = "rohit91jacob"
}

variable "force_destroy" {
  description = "Let terraform destroy delete non-empty buckets (keep false outside throwaway dev)."
  type        = bool
  default     = false
}

variable "emr_release_label" {
  description = "EMR Serverless release (Spark 3.5.8 + Iceberg 1.10.1 on emr-7.14.0)."
  type        = string
  default     = "emr-7.14.0"
}

variable "emr_max_cpu" {
  description = "EMR Serverless maximum capacity: vCPU (cost guardrail)."
  type        = string
  default     = "16 vCPU"
}

variable "emr_max_memory" {
  description = "EMR Serverless maximum capacity: memory (cost guardrail)."
  type        = string
  default     = "64 GB"
}

variable "athena_bytes_scanned_cutoff" {
  description = "Per-query Athena scan limit in bytes (cost guardrail)."
  type        = number
  default     = 10737418240
}

variable "monthly_budget_usd" {
  description = "Monthly AWS Budget for resources tagged project=<project>."
  type        = number
  default     = 25
}

variable "notification_emails" {
  description = "Recipients for pipeline failures and budget alerts."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for Step Functions and CodeBuild."
  type        = number
  default     = 365
}

variable "enable_schedule" {
  description = "Enable the weekly EventBridge schedule (the dataset is static, so off by default)."
  type        = bool
  default     = false
}

variable "enable_github_oidc" {
  description = "Create the GitHub Actions OIDC deploy role."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "Repository allowed to assume the deploy role."
  type        = string
  default     = "rohit91jacob/edtech-learning-analytics-aws"
}

variable "create_github_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider (false if the account already has one)."
  type        = bool
  default     = true
}

variable "existing_github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN when create_github_oidc_provider = false."
  type        = string
  default     = ""
}

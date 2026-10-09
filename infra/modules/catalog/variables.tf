variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "lake_bucket" {
  description = "Iceberg warehouse bucket."
  type        = string
}

variable "athena_results_bucket" {
  description = "Bucket for Athena query results."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for Athena result encryption."
  type        = string
}

variable "bytes_scanned_cutoff_per_query" {
  description = "Athena cancels any query that would scan more than this many bytes (cost guardrail)."
  type        = number
  default     = 10737418240 # 10 GiB; the full OULAD silver layer is well under 1 GiB
}

variable "force_destroy" {
  description = "Allow destroying the workgroup with saved queries (dev only)."
  type        = bool
  default     = false
}

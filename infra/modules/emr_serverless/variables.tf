variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "release_label" {
  description = "EMR release; emr-7.14.0 ships Spark 3.5.8 and Iceberg 1.10.1, matching the local pins."
  type        = string
  default     = "emr-7.14.0"
  validation {
    condition     = can(regex("^emr-7\\.", var.release_label))
    error_message = "The jobs target the EMR 7.x line (Spark 3.5, Python 3.9)."
  }
}

variable "architecture" {
  description = "ARM64 (Graviton) is cheaper per vCPU-hour than X86_64 for the same jobs."
  type        = string
  default     = "ARM64"
}

variable "max_cpu" {
  description = "Maximum vCPU across all running jobs (cost guardrail)."
  type        = string
  default     = "16 vCPU"
}

variable "max_memory" {
  description = "Maximum memory across all running jobs (cost guardrail)."
  type        = string
  default     = "64 GB"
}

variable "idle_timeout_minutes" {
  description = "Stop the application after this many idle minutes."
  type        = number
  default     = 10
}

variable "lake_bucket" {
  description = "Lake bucket name (warehouse and EMR logs)."
  type        = string
}

variable "lake_bucket_arn" {
  description = "Lake bucket ARN."
  type        = string
}

variable "raw_bucket_arn" {
  description = "Raw bucket ARN."
  type        = string
}

variable "code_bucket_arn" {
  description = "Code bucket ARN."
  type        = string
}

variable "silver_database" {
  description = "Glue database the Spark jobs write Iceberg tables into."
  type        = string
}

variable "kms_key_arn" {
  description = "Project data key."
  type        = string
}

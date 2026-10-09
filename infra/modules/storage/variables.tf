variable "project" {
  description = "Project slug used in resource names."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroying non-empty buckets (dev only)."
  type        = bool
  default     = false
}

variable "access_log_retention_days" {
  description = "Days to keep S3 server access logs."
  type        = number
  default     = 90
}

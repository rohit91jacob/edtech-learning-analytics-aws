variable "name" {
  description = "Globally unique bucket name."
  type        = string
}

variable "purpose" {
  description = "Short purpose tag (raw, lake, code, athena-results)."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key used for SSE-KMS."
  type        = string
}

variable "access_log_bucket" {
  description = "Bucket that receives this bucket's server access logs."
  type        = string
}

variable "noncurrent_version_days" {
  description = "Days to keep non-current object versions."
  type        = number
  default     = 30
}

variable "expire_current_after_days" {
  description = "Expire current objects after this many days (null keeps them)."
  type        = number
  default     = null
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete a non-empty bucket (dev only)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to the bucket."
  type        = map(string)
  default     = {}
}

variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "github_repository" {
  description = "owner/name of the repository allowed to assume the deploy role."
  type        = string
}

variable "github_environment" {
  description = "GitHub Actions environment the workflow must run in."
  type        = string
  default     = "aws-dev"
}

variable "create_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider (false if it already exists)."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider when create_oidc_provider = false."
  type        = string
  default     = ""
}

variable "code_bucket_arn" {
  description = "Code bucket ARN."
  type        = string
}

variable "raw_bucket_arn" {
  description = "Raw bucket ARN."
  type        = string
}

variable "state_machine_arn" {
  description = "Pipeline state machine ARN."
  type        = string
}

variable "kms_key_arn" {
  description = "Project data key."
  type        = string
}

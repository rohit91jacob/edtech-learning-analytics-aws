variable "project" {
  description = "Project slug (also the value of the project cost-allocation tag)."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly budget for resources tagged with this project."
  type        = number
  default     = 25
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "The budget must be positive."
  }
}

variable "alert_emails" {
  description = "Email recipients for budget alerts."
  type        = list(string)
  default     = []
}

variable "sns_topic_arn" {
  description = "SNS topic that also receives budget alerts."
  type        = string
}

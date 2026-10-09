# Cost guardrails: a monthly AWS Budget scoped to this project's cost-allocation tag, alerting at
# 80% of actual spend and 100% of forecast spend (email and the pipeline SNS topic).

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-${var.environment}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:project$%s", var.project)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
    subscriber_sns_topic_arns  = [var.sns_topic_arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alert_emails
    subscriber_sns_topic_arns  = [var.sns_topic_arn]
  }
}

# Step Functions state machine (definition shared with the local runner), the CodeBuild project
# that runs dbt against Athena, failure notifications, an optional weekly schedule and an alarm.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition
  name       = "${var.project}-${var.environment}"
  glue_arn   = "arn:${local.partition}:glue:${local.region}:${local.account_id}"
  # Iceberg on EMR 7.x: the runtime jar ships in the image; --py-files carries our package.
  spark_submit_parameters = join(" ", [
    "--conf spark.jars=/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar",
    "--py-files s3://${var.code_bucket}/jobs/edtech_spark.zip",
    "--conf spark.executor.cores=4 --conf spark.executor.memory=8g",
    "--conf spark.driver.cores=2 --conf spark.driver.memory=4g",
    "--conf spark.dynamicAllocation.maxExecutors=3",
  ])
}

# ---------------------------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------------------------
resource "aws_sns_topic" "pipeline" {
  name              = "${local.name}-pipeline"
  kms_master_key_id = var.kms_key_arn
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.notification_emails)
  topic_arn = aws_sns_topic.pipeline.arn
  protocol  = "email"
  endpoint  = each.value
}

# ---------------------------------------------------------------------------------------------
# CodeBuild: dbt build --target athena (models + tests). Source is the dbt project zip that the
# deploy workflow uploads to the code bucket.
# ---------------------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/${var.project}/${var.environment}/codebuild/dbt"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${local.name}-dbt-codebuild"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dbt.arn}:*"]
  }
  statement {
    sid       = "ReadDbtProject"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${var.code_bucket_arn}/dbt/*"]
  }
  statement {
    sid       = "ListBuckets"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.lake_bucket_arn, var.athena_results_bucket_arn]
  }
  statement {
    sid       = "AthenaResultsAndDbtTables"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${var.athena_results_bucket_arn}/*", "${var.lake_bucket_arn}/warehouse/dbt/*"]
  }
  statement {
    sid       = "ReadSilver"
    actions   = ["s3:GetObject"]
    resources = ["${var.lake_bucket_arn}/warehouse/*"]
  }
  statement {
    sid = "Athena"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = [var.athena_workgroup_arn]
  }
  statement {
    sid = "GlueForDbt"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:BatchDeleteTable",
      "glue:GetPartitions",
      "glue:BatchCreatePartition",
    ]
    resources = concat(
      ["${local.glue_arn}:catalog"],
      [for db in var.glue_database_names : "${local.glue_arn}:database/${db}"],
      [for db in var.glue_database_names : "${local.glue_arn}:table/${db}/*"],
    )
  }
  statement {
    sid       = "UseProjectKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "dbt-athena"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

resource "aws_codebuild_project" "dbt" {
  name           = "${local.name}-dbt"
  description    = "dbt build (models and tests) for the OULAD marts on Athena"
  service_role   = aws_iam_role.codebuild.arn
  build_timeout  = 30
  encryption_key = var.kms_key_arn

  source {
    type      = "S3"
    location  = "${var.code_bucket}/dbt/edtech-dbt.zip"
    buildspec = file("${path.module}/buildspec.yml")
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false

    environment_variable {
      name  = "EDTECH_ATHENA_SCHEMA"
      value = replace(local.name, "-", "_")
    }
    environment_variable {
      name  = "EDTECH_SILVER_SCHEMA"
      value = var.glue_database_names["silver"]
    }
    environment_variable {
      name  = "EDTECH_ATHENA_WORKGROUP"
      value = var.athena_workgroup_name
    }
    environment_variable {
      name  = "EDTECH_ATHENA_STAGING_DIR"
      value = "s3://${var.athena_results_bucket}/dbt/"
    }
    environment_variable {
      name  = "EDTECH_ATHENA_DATA_DIR"
      value = "s3://${var.lake_bucket}/warehouse/dbt/"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.dbt.name
      status     = "ENABLED"
    }
    s3_logs {
      status = "DISABLED"
    }
  }
}

# ---------------------------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/${var.project}/${var.environment}/states/pipeline"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-pipeline-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn" {
  #checkov:skip=CKV_AWS_111:CloudWatch Logs delivery and X-Ray APIs do not support resource-level permissions ("*" is required by AWS).
  #checkov:skip=CKV_AWS_356:Same as above: log-delivery and X-Ray actions only accept "*".
  statement {
    sid       = "RunEmrServerlessJobs"
    actions   = ["emr-serverless:StartJobRun"]
    resources = [var.emr_application_arn]
  }
  statement {
    sid       = "TrackEmrServerlessJobs"
    actions   = ["emr-serverless:GetJobRun", "emr-serverless:CancelJobRun"]
    resources = ["${var.emr_application_arn}/jobruns/*"]
  }
  statement {
    sid       = "PassJobRole"
    actions   = ["iam:PassRole"]
    resources = [var.emr_job_role_arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["emr-serverless.amazonaws.com"]
    }
  }
  statement {
    sid       = "RunDbtBuild"
    actions   = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.dbt.arn]
  }
  statement {
    sid     = "SyncIntegrationRules"
    actions = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = [
      "arn:${local.partition}:events:${local.region}:${local.account_id}:rule/StepFunctionsGetEventsForEMRServerlessJobRule",
      "arn:${local.partition}:events:${local.region}:${local.account_id}:rule/StepFunctionsGetEventsForCodeBuildStartBuildRule",
    ]
  }
  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.pipeline.arn]
  }
  statement {
    sid       = "UseProjectKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
  statement {
    sid = "ExecutionLogs"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "pipeline"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name}-pipeline"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  # Same file the local runner executes (src/edtech_analytics/orchestration/pipeline.asl.json).
  definition = templatefile(var.definition_path, {
    application_id          = var.emr_application_id
    job_role_arn            = var.emr_job_role_arn
    code_uri                = "s3://${var.code_bucket}/jobs"
    catalog                 = "glue"
    silver_db               = var.glue_database_names["silver"]
    warehouse_uri           = "s3://${var.lake_bucket}/warehouse"
    raw_uri                 = "s3://${var.raw_bucket}/oulad"
    logs_uri                = "s3://${var.lake_bucket}/emr-logs/"
    spark_submit_parameters = local.spark_submit_parameters
    dbt_project_name        = aws_codebuild_project.dbt.name
    topic_arn               = aws_sns_topic.pipeline.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration {
    enabled = true
  }

  encryption_configuration {
    type                              = "CUSTOMER_MANAGED_KMS_KEY"
    kms_key_id                        = var.kms_key_arn
    kms_data_key_reuse_period_seconds = 300
  }

  depends_on = [aws_iam_role_policy.sfn]
}

# ---------------------------------------------------------------------------------------------
# Weekly schedule (off by default: the data is a static 2013-2014 release).
# ---------------------------------------------------------------------------------------------
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-pipeline-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "start-pipeline"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "weekly" {
  name                         = "${local.name}-pipeline-weekly"
  description                  = "Weekly rebuild of the OULAD marts"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = var.enable_schedule ? "ENABLED" : "DISABLED"
  kms_key_arn                  = var.kms_key_arn

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.pipeline.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ trigger = "schedule" })
    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "failed" {
  alarm_name          = "${local.name}-pipeline-failed"
  alarm_description   = "A pipeline execution failed or timed out"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.pipeline.arn]
}

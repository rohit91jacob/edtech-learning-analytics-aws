# EMR Serverless Spark application plus the job execution role the Spark jobs run as.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition
  name       = "${var.project}-${var.environment}"
  glue_arn   = "arn:${local.partition}:glue:${local.region}:${local.account_id}"
}

resource "aws_emrserverless_application" "spark" {
  name          = "${local.name}-spark"
  release_label = var.release_label
  type          = "spark"
  architecture  = var.architecture

  # Hard ceiling on what all concurrent job runs together may use: the main cost guardrail.
  maximum_capacity {
    cpu    = var.max_cpu
    memory = var.max_memory
  }

  # No pre-initialised (always billed) capacity; workers start on demand.
  auto_start_configuration {
    enabled = true
  }
  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = var.idle_timeout_minutes
  }

  monitoring_configuration {
    s3_monitoring_configuration {
      log_uri            = "s3://${var.lake_bucket}/emr-logs/"
      encryption_key_arn = var.kms_key_arn
    }
  }
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:emr-serverless:${local.region}:${local.account_id}:/applications/*"]
    }
  }
}

resource "aws_iam_role" "job" {
  name                 = "${local.name}-emr-job"
  description          = "Runtime role for the OULAD Spark jobs on EMR Serverless"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "job" {
  statement {
    sid       = "ListProjectBuckets"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.raw_bucket_arn, var.lake_bucket_arn, var.code_bucket_arn]
  }
  statement {
    sid       = "ReadRawAndCode"
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/oulad/*", "${var.code_bucket_arn}/jobs/*"]
  }
  statement {
    sid       = "ReadWriteWarehouseAndLogs"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${var.lake_bucket_arn}/warehouse/*", "${var.lake_bucket_arn}/emr-logs/*"]
  }
  statement {
    sid = "IcebergGlueCatalog"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:GetPartitions",
    ]
    resources = [
      "${local.glue_arn}:catalog",
      "${local.glue_arn}:database/${var.silver_database}",
      "${local.glue_arn}:table/${var.silver_database}/*",
    ]
  }
  statement {
    sid       = "UseProjectKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "job" {
  name   = "spark-job-access"
  role   = aws_iam_role.job.id
  policy = data.aws_iam_policy_document.job.json
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition
  prefix     = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------------------------
# One customer-managed key for the project's data at rest (S3, logs, SNS, Step Functions,
# CodeBuild artefacts). Rotation is on; the key policy only grants the account (delegating to
# IAM) and the AWS services that write encrypted data on our behalf, each scoped to this account.
# ---------------------------------------------------------------------------------------------
data "aws_iam_policy_document" "kms" {
  #checkov:skip=CKV_AWS_109:Key policies must name the key itself as "*"; access is delegated to IAM in this account.
  #checkov:skip=CKV_AWS_111:Same as above: "*" in a key policy means "this key".
  #checkov:skip=CKV_AWS_356:Same as above: "*" in a key policy means "this key".
  statement {
    sid       = "AccountAdministersKeyThroughIam"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogsEncryptsProjectLogGroups"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/${var.project}/${var.environment}/*"]
    }
  }

  statement {
    sid       = "AlarmsAndBudgetsPublishToEncryptedTopic"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "budgets.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "data" {
  description             = "${local.prefix} data at rest (S3, logs, SNS, Step Functions)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms.json
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}

# ---------------------------------------------------------------------------------------------
# Access-log sink. S3 server access logging only delivers to SSE-S3 buckets, and a log bucket
# does not log to itself.
# ---------------------------------------------------------------------------------------------
resource "aws_s3_bucket" "logs" {
  #checkov:skip=CKV_AWS_145:S3 server access log delivery does not support SSE-KMS target buckets; SSE-S3 (AES256) is used.
  #checkov:skip=CKV_AWS_18:This is the access-log sink; logging it to itself would loop.
  #checkov:skip=CKV2_AWS_62:No consumer reacts to log-object events.
  #checkov:skip=CKV_AWS_144:Access logs are not replicated cross-region; they expire after the retention window.
  bucket        = "${local.prefix}-access-logs-${local.account_id}"
  force_destroy = var.force_destroy
  tags          = { Name = "${local.prefix}-access-logs", purpose = "access-logs" }
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-access-logs"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    expiration {
      days = var.access_log_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "logs" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
  statement {
    sid       = "AllowServerAccessLogDelivery"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/s3-access/*"]
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket     = aws_s3_bucket.logs.id
  policy     = data.aws_iam_policy_document.logs.json
  depends_on = [aws_s3_bucket_public_access_block.logs]
}

# ---------------------------------------------------------------------------------------------
# Data buckets.
# ---------------------------------------------------------------------------------------------
module "raw" {
  source            = "../s3_bucket"
  name              = "${local.prefix}-raw-${local.account_id}"
  purpose           = "raw"
  kms_key_arn       = aws_kms_key.data.arn
  access_log_bucket = aws_s3_bucket.logs.id
  force_destroy     = var.force_destroy
}

module "lake" {
  source            = "../s3_bucket"
  name              = "${local.prefix}-lake-${local.account_id}"
  purpose           = "lake"
  kms_key_arn       = aws_kms_key.data.arn
  access_log_bucket = aws_s3_bucket.logs.id
  force_destroy     = var.force_destroy
  # Iceberg rewrites metadata on every commit; old versions are only needed briefly.
  noncurrent_version_days = 7
}

module "code" {
  source            = "../s3_bucket"
  name              = "${local.prefix}-code-${local.account_id}"
  purpose           = "code"
  kms_key_arn       = aws_kms_key.data.arn
  access_log_bucket = aws_s3_bucket.logs.id
  force_destroy     = var.force_destroy
}

module "athena_results" {
  source                    = "../s3_bucket"
  name                      = "${local.prefix}-athena-results-${local.account_id}"
  purpose                   = "athena-results"
  kms_key_arn               = aws_kms_key.data.arn
  access_log_bucket         = aws_s3_bucket.logs.id
  force_destroy             = var.force_destroy
  expire_current_after_days = 30
  noncurrent_version_days   = 1
}

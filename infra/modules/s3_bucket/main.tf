# One hardened data bucket: SSE-KMS with a bucket key, versioning, public access blocked,
# bucket-owner-enforced ownership, a TLS-only bucket policy, server access logging and lifecycle.

resource "aws_s3_bucket" "this" {
  #checkov:skip=CKV2_AWS_62:No consumer reacts to object events; Step Functions orchestrates the pipeline, not S3 notifications.
  #checkov:skip=CKV_AWS_144:Cross-region replication would double storage cost for a public, re-downloadable dataset; versioning covers accidental deletes.
  bucket        = var.name
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { Name = var.name, purpose = var.purpose })
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "this" {
  bucket        = aws_s3_bucket.this.id
  target_bucket = var.access_log_bucket
  target_prefix = "s3-access/${var.name}/"
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "abort-uploads-expire-old-versions"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    dynamic "expiration" {
      for_each = var.expire_current_after_days == null ? [] : [var.expire_current_after_days]
      content {
        days = expiration.value
      }
    }
  }
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]
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
}

resource "aws_s3_bucket_policy" "this" {
  bucket     = aws_s3_bucket.this.id
  policy     = data.aws_iam_policy_document.this.json
  depends_on = [aws_s3_bucket_public_access_block.this]
}

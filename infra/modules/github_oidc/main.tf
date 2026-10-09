# GitHub Actions OIDC federation for .github/workflows/deploy.yml: no static AWS keys.
# The deploy role can only upload job artefacts, land raw data and start the pipeline;
# infrastructure changes stay with a human running terraform apply.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only workflow runs in the protected "aws-dev" environment of this repository.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.project}-${var.environment}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "UploadArtefactsAndRawData"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${var.code_bucket_arn}/jobs/*", "${var.code_bucket_arn}/dbt/*", "${var.raw_bucket_arn}/oulad/*"]
  }
  statement {
    sid       = "ListTargets"
    actions   = ["s3:ListBucket"]
    resources = [var.code_bucket_arn, var.raw_bucket_arn]
  }
  statement {
    sid       = "StartPipeline"
    actions   = ["states:StartExecution", "states:DescribeExecution"]
    resources = [var.state_machine_arn, "${replace(var.state_machine_arn, ":stateMachine:", ":execution:")}:*"]
  }
  statement {
    sid       = "EncryptUploads"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-artefacts-and-run"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

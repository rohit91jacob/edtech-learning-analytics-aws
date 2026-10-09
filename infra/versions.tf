terraform {
  required_version = ">= 1.9, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
  }

  # Remote state for a real deployment (S3 native locking; create the bucket first):
  # backend "s3" {
  #   bucket       = "<state-bucket>"
  #   key          = "edtech-learning-analytics/dev.tfstate"
  #   region       = "eu-west-2"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project             = var.project
      environment         = var.environment
      owner               = var.owner
      managed-by          = "terraform"
      repository          = "github.com/rohit91jacob/edtech-learning-analytics-aws"
      data-classification = "public-anonymised"
      cost-center         = "portfolio"
    }
  }
}

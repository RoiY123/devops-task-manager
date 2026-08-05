provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = "task-manager"
      Environment = "production"
      ManagedBy   = "Terraform"
      Purpose     = "TerraformState"
    }
  }
}

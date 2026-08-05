terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket       = "task-manager-tfstate-359642223744-il-central-1"
    key          = "production/terraform.tfstate"
    region       = "il-central-1"
    profile      = "task-manager-terraform"
    encrypt      = true
    use_lockfile = true
  }
}

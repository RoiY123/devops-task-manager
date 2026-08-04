variable "aws_region" {
  description = "AWS region where the task manager infrastructure is deployed"
  type        = string
  default     = "il-central-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used by Terraform"
  type        = string
  default     = "task-manager-terraform"
}

variable "project_name" {
  description = "Name used to identify task manager infrastructure resources"
  type        = string
  default     = "task-manager"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

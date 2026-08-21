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

variable "admin_allowed_cidr" {
  description = "Public IPv4 CIDR allowed to access administrative services"
  type        = string

  validation {
    condition     = can(cidrnetmask(var.admin_allowed_cidr)) && endswith(var.admin_allowed_cidr, "/32")
    error_message = "admin_allowed_cidr must be a valid single-host IPv4 CIDR ending in /32."
  }
}

variable "db_name" {
  description = "Name of the application database in the production RDS instance"
  type        = string
}

variable "db_master_username" {
  description = "Master username of the production RDS instance"
  type        = string
}

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

variable "ssh_allowed_cidr" {
  description = "Public IPv4 CIDR allowed to connect to the EC2 instance over SSH"
  type        = string

  validation {
    condition     = can(cidrnetmask(var.ssh_allowed_cidr)) && endswith(var.ssh_allowed_cidr, "/32")
    error_message = "ssh_allowed_cidr must be a valid single-host IPv4 CIDR ending in /32."
  }
}

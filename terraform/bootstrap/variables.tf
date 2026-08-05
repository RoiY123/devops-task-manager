variable "aws_region" {
  description = "AWS region containing the Terraform state bucket"
  type        = string
  default     = "il-central-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used to create the backend resources"
  type        = string
  default     = "task-manager-terraform"
}

variable "state_bucket_name" {
  description = "Globally unique name of the S3 bucket used for Terraform state"
  type        = string

  validation {
    condition = (
      length(var.state_bucket_name) >= 3 &&
      length(var.state_bucket_name) <= 63 &&
      can(regex(
        "^[a-z0-9][a-z0-9.-]*[a-z0-9]$",
        var.state_bucket_name
      ))
    )

    error_message = "state_bucket_name must be a valid lowercase S3 bucket name between 3 and 63 characters."
  }
}

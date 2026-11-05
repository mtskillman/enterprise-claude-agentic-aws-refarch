variable "project_name" {
  type        = string
  description = "Project name identifier"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "aws_region" {
  type        = string
  description = "AWS region for CloudWatch metrics and dashboards"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
}

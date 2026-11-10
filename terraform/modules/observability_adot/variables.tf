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

variable "state_machine_arn" {
  type        = string
  description = "ARN of the Step Functions agent state machine for execution health metrics"
}

variable "primary_model_id" {
  type        = string
  description = "Primary Claude model or inference profile ID (Bedrock ModelId metric dimension)"
}

variable "fallback_model_id" {
  type        = string
  description = "Fallback Claude model or inference profile ID (Bedrock ModelId metric dimension)"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
}

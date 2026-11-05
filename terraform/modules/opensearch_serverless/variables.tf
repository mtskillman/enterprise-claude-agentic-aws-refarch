variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "kms_key_arn" {
  description = "ARN of the Customer Managed KMS Key (CMK) used to encrypt the OpenSearch Serverless collection."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the private OpenSearch Serverless VPC Endpoint is provisioned."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the OpenSearch Serverless VPC Endpoint."
  type        = list(string)
}

variable "vpce_security_group_ids" {
  description = "Security Group IDs attached to the OpenSearch Serverless VPC Endpoint."
  type        = list(string)
}

variable "orchestrator_role_arn" {
  description = "IAM Role ARN of the Orchestrator Lambda (granted read-only vector & lexical search access)."
  type        = string
}

variable "ingestion_role_arn" {
  description = "IAM Role ARN of the Ingestion Lambda (granted index creation and document write access)."
  type        = string
}

variable "tags" {
  type = map(string)
}

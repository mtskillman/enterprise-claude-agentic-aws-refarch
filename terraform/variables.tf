variable "aws_region" {
  description = "The AWS region to deploy the GenAI reference architecture into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g., dev, staging, prod)."
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project identifier prefix for resource naming and tagging."
  type        = string
  default     = "claude-agentic-platform"
}

variable "vpc_cidr" {
  description = "CIDR block for the isolated GenAI private VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "primary_claude_model_id" {
  description = "Bedrock Model ID for the primary reasoning agent (Anthropic Claude 3.5 Sonnet)."
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "fallback_claude_model_id" {
  description = "Bedrock Model ID for fallback reasoning (Anthropic Claude 3.5 Haiku)."
  type        = string
  default     = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "embedding_model_id" {
  description = "Bedrock Model ID for generating 1,024-dimensional document and query embeddings."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "tags" {
  description = "Global tags to apply across all deployed AWS resources."
  type        = map(string)
  default = {
    Project      = "enterprise-claude-agentic-aws-refarch"
    ManagedBy    = "Terraform"
    Architecture = "Serverless-GenAI"
  }
}

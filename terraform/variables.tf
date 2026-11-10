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

variable "opensearch_standby_replicas" {
  description = "OpenSearch Serverless standby replicas. ENABLED for production (multi-AZ, 2-OCU minimum, about $350/month idle in us-east-1). DISABLED for dev/test (about half the OCU minimum, no AZ redundancy). Changing this replaces the collection and its index."
  type        = string
  default     = "ENABLED"

  validation {
    condition     = contains(["ENABLED", "DISABLED"], var.opensearch_standby_replicas)
    error_message = "opensearch_standby_replicas must be ENABLED or DISABLED."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the isolated GenAI private VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "primary_claude_model_id" {
  description = "Bedrock cross-Region inference profile ID (or base model ID) for the primary reasoning agent."
  type        = string
  default     = "us.anthropic.claude-sonnet-5"
}

variable "fallback_claude_model_id" {
  description = "Bedrock cross-Region inference profile ID (or base model ID) for fallback reasoning."
  type        = string
  default     = "us.anthropic.claude-haiku-5-5"
}

variable "embedding_model_id" {
  description = "Bedrock Model ID for generating 1,024-dimensional document and query embeddings."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "model_pricing_usd_per_1k_tokens" {
  description = "Per-1,000-token USD rates keyed by the model or inference profile ID used at runtime, for EstimatedCostUSD attribution. Take rates from the Amazon Bedrock pricing page for your Region and profile scope. Unpriced models report a cost of 0."
  type = map(object({
    input  = number
    output = number
  }))
  default = {}
}

variable "document_admin_principal_arns" {
  description = "IAM principal ARNs (roles or users, not session ARNs) allowed to upload documents under any tenants/<tenant_id>/ prefix. Principals tagged with tenant_id can always upload under their own prefix."
  type        = list(string)
  default     = []
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

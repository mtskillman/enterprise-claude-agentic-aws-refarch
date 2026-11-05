output "kms_key_arn" {
  description = "Customer Managed Key (KMS CMK) ARN used across all GenAI services."
  value       = module.security.kms_key_arn
}

output "opensearch_collection_endpoint" {
  description = "OpenSearch Serverless Vector Collection endpoint."
  value       = module.opensearch_serverless.collection_endpoint
}

output "opensearch_collection_arn" {
  description = "OpenSearch Serverless Vector Collection ARN."
  value       = module.opensearch_serverless.collection_arn
}

output "bedrock_guardrail_arn" {
  description = "Bedrock Enterprise Guardrail ARN."
  value       = module.bedrock_agent.guardrail_arn
}

output "bedrock_guardrail_version" {
  description = "Bedrock Enterprise Guardrail Active Version."
  value       = module.bedrock_agent.guardrail_version
}

output "step_functions_state_machine_arn" {
  description = "Step Functions State Machine ARN orchestrating the agentic reasoning loop."
  value       = module.orchestrator_step_functions.state_machine_arn
}

output "knowledge_bucket_name" {
  description = "S3 bucket for document ingestion and vector indexing."
  value       = aws_s3_bucket.knowledge_documents.bucket
}

output "orchestrator_lambda_arn" {
  description = "Orchestrator Lambda Function ARN."
  value       = aws_lambda_function.orchestrator.arn
}

output "telemetry_dashboard_name" {
  description = "CloudWatch Telemetry & GenAI Cost Dashboard Name."
  value       = module.observability.dashboard_name
}

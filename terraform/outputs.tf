output "kms_key_arn" {
  description = "Customer Managed Key (KMS CMK) ARN used across all GenAI services."
  value       = module.security.kms_key_arn
}

output "api_gateway_endpoint" {
  description = "Authenticated HTTP API endpoint for starting tenant-bound agent executions."
  value       = "${aws_apigatewayv2_api.agent_api.api_endpoint}/v1/agent/executions"
}

output "api_gateway_poll_endpoint" {
  description = "Authenticated HTTP API route template for polling execution results."
  value       = "${aws_apigatewayv2_api.agent_api.api_endpoint}/v1/agent/executions/{execution_id}"
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID governing tenant identity (`custom:tenant_id` claim)."
  value       = aws_cognito_user_pool.tenant_identity_pool.id
}

output "opensearch_collection_endpoint" {
  description = "OpenSearch Serverless Vector Collection private endpoint."
  value       = module.opensearch_serverless.collection_endpoint
}

output "opensearch_collection_arn" {
  description = "OpenSearch Serverless Vector Collection ARN."
  value       = module.opensearch_serverless.collection_arn
}

output "opensearch_vpc_endpoint_id" {
  description = "Private Interface VPC Endpoint ID for OpenSearch Serverless (`AllowFromPublic = false`)."
  value       = module.opensearch_serverless.vpc_endpoint_id
}

output "opensearch_dependencies_layer_arn" {
  description = "Lambda Layer ARN providing opensearch-py and requests-aws4auth dependencies."
  value       = aws_lambda_layer_version.opensearch_dependencies.arn
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
  description = "S3 bucket for document ingestion (`s3://<bucket>/tenants/<tenant_id>/...`)."
  value       = aws_s3_bucket.knowledge_documents.bucket
}

output "orchestrator_lambda_arn" {
  description = "Orchestrator Lambda Function ARN (Read-Only AOSS search, zero S3 access)."
  value       = aws_lambda_function.orchestrator.arn
}

output "ingestion_lambda_arn" {
  description = "Ingestion & Index Bootstrapper Lambda Function ARN (Titan Embed v2 & AOSS write)."
  value       = aws_lambda_function.ingestion.arn
}

output "telemetry_dashboard_name" {
  description = "CloudWatch Telemetry & GenAI Cost Dashboard Name."
  value       = module.observability.dashboard_name
}

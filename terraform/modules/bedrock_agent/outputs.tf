output "guardrail_arn" {
  value       = aws_bedrock_guardrail.enterprise_guardrail.guardrail_arn
  description = "ARN of the Amazon Bedrock Guardrail."
}

output "guardrail_version" {
  value       = aws_bedrock_guardrail_version.v1.version
  description = "Active version of the Amazon Bedrock Guardrail."
}

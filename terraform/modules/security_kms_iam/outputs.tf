output "kms_key_arn" {
  value       = aws_kms_key.genai_key.arn
  description = "ARN of the Customer Managed Key (KMS CMK)."
}

output "kms_key_id" {
  value       = aws_kms_key.genai_key.key_id
  description = "Key ID of the Customer Managed Key."
}

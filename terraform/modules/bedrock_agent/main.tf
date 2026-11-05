# Amazon Bedrock Guardrail for Enterprise Safety and Data Protection
resource "aws_bedrock_guardrail" "enterprise_guardrail" {
  name                      = "${var.project_name}-guardrail"
  description               = "Enterprise guardrail enforcing PII redaction and prompt injection defense"
  blocked_input_messaging   = "Request blocked: Content violates enterprise AI acceptable use policies."
  blocked_outputs_messaging = "Response blocked: Generated output contains restricted sensitive information."
  kms_key_arn               = var.kms_key_arn

  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-guardrail"
  })
}

resource "aws_bedrock_guardrail_version" "v1" {
  guardrail_arn = aws_bedrock_guardrail.enterprise_guardrail.guardrail_arn
  description   = "Version 1.0.0"
}

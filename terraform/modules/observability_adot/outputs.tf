output "dashboard_arn" {
  description = "CloudWatch GenAI Telemetry Dashboard ARN"
  value       = aws_cloudwatch_dashboard.genai_dashboard.dashboard_arn
}

output "dashboard_name" {
  description = "CloudWatch GenAI Telemetry Dashboard Name"
  value       = aws_cloudwatch_dashboard.genai_dashboard.dashboard_name
}

resource "aws_cloudwatch_dashboard" "genai_dashboard" {
  dashboard_name = "${var.project_name}-telemetry"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InvocationLatency", "ModelId", "anthropic.claude-3-5-sonnet-20241022-v2:0", { stat = "p95", period = 60 }],
            ["...", "anthropic.claude-3-5-haiku-20241022-v1:0", { stat = "p95", period = 60 }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "Claude Model Latency (P95 ms)"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InputTokenCount", { stat = "Sum", period = 300 }],
            [".", "OutputTokenCount", { stat = "Sum", period = 300 }]
          ]
          view    = "timeSeries"
          stacked = true
          region  = "us-east-1"
          title   = "Token Consumption (Input vs. Output Tokens)"
        }
      }
    ]
  })
}

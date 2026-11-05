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
            ["EnterpriseClaude/AgenticWorkflows", "EstimatedCostUSD", "TenantId", "default", { stat = "Sum", period = 300, label = "Estimated FinOps Cost (USD)" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Real-Time FinOps: GenAI Invocations Cost ($ USD) by Tenant"
          yAxis = {
            left = {
              label     = "USD ($)"
              showUnits = false
            }
          }
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
            ["EnterpriseClaude/AgenticWorkflows", "InputTokens", "TenantId", "default", { stat = "Sum", period = 300, label = "Input Tokens" }],
            [".", "OutputTokens", ".", ".", { stat = "Sum", period = 300, label = "Output Tokens" }],
            [".", "TotalTokens", ".", ".", { stat = "Sum", period = 300, label = "Total Tokens" }]
          ]
          view    = "timeSeries"
          stacked = true
          region  = var.aws_region
          title   = "Token Consumption Breakdown (Input vs. Output Tokens by Tenant)"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InvocationLatency", "ModelId", "anthropic.claude-3-5-sonnet-20241022-v2:0", { stat = "p95", period = 60, label = "Claude 3.5 Sonnet P95" }],
            ["...", "anthropic.claude-3-5-haiku-20241022-v1:0", { stat = "p95", period = 60, label = "Claude 3.5 Haiku Fallback P95" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Claude Model Latency (P95 ms)"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", "${var.project_name}-orchestrator", { stat = "Sum", period = 300, label = "Executions Succeeded" }],
            [".", "ExecutionsFailed", ".", ".", { stat = "Sum", period = 300, label = "Executions Failed" }],
            [".", "ExecutionsTimedOut", ".", ".", { stat = "Sum", period = 300, label = "Executions Timed Out" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Step Functions Agentic Execution Health"
        }
      }
    ]
  })
}

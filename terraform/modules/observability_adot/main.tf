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
            [{ expression = "SEARCH('{EnterpriseClaude/AgenticWorkflows,TenantId} MetricName=\"EstimatedCostUSD\"', 'Sum', 300)", id = "cost_by_tenant", period = 300 }]
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
            [{ expression = "SEARCH('{EnterpriseClaude/AgenticWorkflows,TenantId} MetricName=\"TotalTokens\"', 'Sum', 300)", id = "tokens_by_tenant", period = 300 }]
          ]
          view    = "timeSeries"
          stacked = true
          region  = var.aws_region
          title   = "Token Consumption Breakdown (Total Tokens by Tenant)"
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
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn, { stat = "Sum", period = 300, label = "Executions Succeeded" }],
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

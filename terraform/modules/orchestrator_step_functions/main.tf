data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "sfn_role" {
  name = "${var.project_name}-sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.${data.aws_region.current.name}.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_policy" "sfn_policy" {
  name = "${var.project_name}-sfn-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [var.agent_lambda_arn]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*"
        ]
        Resource = [var.kms_key_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sfn_attach" {
  role       = aws_iam_role.sfn_role.name
  policy_arn = aws_iam_policy.sfn_policy.arn
}

resource "aws_sfn_state_machine" "agentic_loop" {
  name     = "${var.project_name}-agent-state-machine"
  role_arn = aws_iam_role.sfn_role.arn

  definition = templatefile("${path.module}/state_machine.asl.json", {
    AgentLambdaArn = var.agent_lambda_arn
  })

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = false
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-agentic-loop"
  })
}

resource "aws_cloudwatch_log_group" "sfn_logs" {
  name              = "/aws/vendedlogs/states/${var.project_name}-${var.environment}"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

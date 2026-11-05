data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Customer Managed Key (CMK) for Enterprise GenAI Data Perimeter
resource "aws_kms_key" "genai_key" {
  description             = "CMK for ${var.project_name} GenAI embeddings, knowledge base, and execution state"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootPermissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.${data.aws_region.current.name}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*"
        ]
        Resource = "*"
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.project_name}-kms-key"
  })
}

resource "aws_kms_alias" "genai_key_alias" {
  name          = "alias/${var.project_name}-${var.environment}"
  target_key_id = aws_kms_key.genai_key.key_id
}

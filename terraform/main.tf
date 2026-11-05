terraform {
  required_version = ">= 1.5.0"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ==============================================================================
# Security & KMS
# ==============================================================================
module "security" {
  source       = "./modules/security_kms_iam"
  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags
}

# ==============================================================================
# Document Ingestion Storage (S3)
# ==============================================================================
resource "aws_s3_bucket" "knowledge_documents" {
  bucket        = "${var.project_name}-docs-${data.aws_caller_identity.current.account_id}"
  force_destroy = false

  tags = merge(var.tags, {
    Name = "${var.project_name}-knowledge-documents"
  })
}

resource "aws_s3_bucket_versioning" "knowledge_documents" {
  bucket = aws_s3_bucket.knowledge_documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "knowledge_documents" {
  bucket = aws_s3_bucket.knowledge_documents.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = module.security.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "knowledge_documents" {
  bucket = aws_s3_bucket.knowledge_documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ==============================================================================
# Lambda Execution Roles & IAM Policies
# ==============================================================================
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_policy" "lambda_genai_policy" {
  name        = "${var.project_name}-lambda-genai-policy"
  description = "Permissions for Claude Bedrock, OpenSearch Serverless, S3, and KMS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ApplyGuardrail"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/*",
          module.bedrock_agent.guardrail_arn
        ]
      },
      {
        Sid    = "OpenSearchServerlessAccess"
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll"
        ]
        Resource = [module.opensearch_serverless.collection_arn]
      },
      {
        Sid    = "S3DocumentAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.knowledge_documents.arn,
          "${aws_s3_bucket.knowledge_documents.arn}/*"
        ]
      },
      {
        Sid    = "KMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = [module.security.kms_key_arn]
      },
      {
        Sid    = "CloudWatchLogsAndTelemetry"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "cloudwatch:PutMetricData",
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_attach_custom" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_genai_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ==============================================================================
# OpenSearch Serverless Vector Collection
# ==============================================================================
module "opensearch_serverless" {
  source                    = "./modules/opensearch_serverless"
  project_name              = var.project_name
  environment               = var.environment
  kms_key_arn               = module.security.kms_key_arn
  lambda_execution_role_arn = aws_iam_role.lambda_exec.arn
  tags                      = var.tags
}

# ==============================================================================
# Bedrock Guardrails Module
# ==============================================================================
module "bedrock_agent" {
  source       = "./modules/bedrock_agent"
  project_name = var.project_name
  kms_key_arn  = module.security.kms_key_arn
  tags         = var.tags
}

# ==============================================================================
# Lambda Functions (Orchestrator & Ingestion)
# ==============================================================================
data "archive_file" "orchestrator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/build/orchestrator.zip"
}

resource "aws_lambda_function" "orchestrator" {
  filename         = data.archive_file.orchestrator_zip.output_path
  function_name    = "${var.project_name}-orchestrator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "orchestrator.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 1024
  source_code_hash = data.archive_file.orchestrator_zip.output_base64sha256

  environment {
    variables = {
      PRIMARY_CLAUDE_MODEL_ID  = var.primary_claude_model_id
      FALLBACK_CLAUDE_MODEL_ID = var.fallback_claude_model_id
      BEDROCK_GUARDRAIL_ID     = element(split("/", module.bedrock_agent.guardrail_arn), length(split("/", module.bedrock_agent.guardrail_arn)) - 1)
      BEDROCK_GUARDRAIL_VER    = module.bedrock_agent.guardrail_version
      OPENSEARCH_ENDPOINT      = module.opensearch_serverless.collection_endpoint
      POWERTOOLS_SERVICE_NAME  = "claude-orchestrator"
      LOG_LEVEL                = "INFO"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_lambda_function" "ingestion" {
  filename         = data.archive_file.orchestrator_zip.output_path
  function_name    = "${var.project_name}-ingestion"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "ingestion.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 180
  memory_size      = 512
  source_code_hash = data.archive_file.orchestrator_zip.output_base64sha256

  environment {
    variables = {
      EMBEDDING_MODEL_ID      = var.embedding_model_id
      OPENSEARCH_ENDPOINT     = module.opensearch_serverless.collection_endpoint
      POWERTOOLS_SERVICE_NAME = "claude-ingestion"
      LOG_LEVEL               = "INFO"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

# ==============================================================================
# S3 Document Ingestion Notification
# ==============================================================================
resource "aws_lambda_permission" "allow_s3_ingestion" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.knowledge_documents.arn
}

resource "aws_s3_bucket_notification" "document_upload_trigger" {
  bucket = aws_s3_bucket.knowledge_documents.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingestion.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_ingestion]
}

# ==============================================================================
# Agentic Step Functions State Machine
# ==============================================================================
module "orchestrator_step_functions" {
  source           = "./modules/orchestrator_step_functions"
  project_name     = var.project_name
  environment      = var.environment
  agent_lambda_arn = aws_lambda_function.orchestrator.arn
  kms_key_arn      = module.security.kms_key_arn
  tags             = var.tags
}

# ==============================================================================
# Observability & CloudWatch Dashboards
# ==============================================================================
module "observability" {
  source       = "./modules/observability_adot"
  project_name = var.project_name
  environment  = var.environment
  kms_key_arn  = module.security.kms_key_arn
  tags         = var.tags
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

# ==============================================================================
# 1. Security & KMS Customer Managed Key (CMK)
# ==============================================================================
module "security" {
  source       = "./modules/security_kms_iam"
  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags
}

# Zero-Trust State Hygiene:
# The secret container is declared with KMS CMK encryption, but the plaintext key
# is NEVER stored or generated in Terraform state. The Gatekeeper Lambda auto-seeds
# the 256-bit secret directly into AWS Secrets Manager upon first run, or operators
# seed/rotate it out-of-band using scripts/seed_hmac_secret.sh.
resource "aws_secretsmanager_secret" "tenant_context_hmac" {
  name                    = "${var.project_name}-${var.environment}-tenant-hmac-secret"
  description             = "HMAC-SHA256 signing key used to cryptographically seal verified tenant identity contexts"
  kms_key_id              = module.security.kms_key_arn
  recovery_window_in_days = 0
  tags                    = var.tags
}

# ==============================================================================
# 2. Private VPC & Zero-Trust Network Isolation
# ==============================================================================
resource "aws_vpc" "genai_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    Name = "${var.project_name}-vpc"
  })
}

resource "aws_subnet" "private_a" {
  vpc_id                  = aws_vpc.genai_vpc.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.project_name}-private-subnet-a"
  })
}

resource "aws_subnet" "private_b" {
  vpc_id                  = aws_vpc.genai_vpc.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 2)
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.project_name}-private-subnet-b"
  })
}

resource "aws_route_table" "private_rt" {
  vpc_id = aws_vpc.genai_vpc.id
  tags = merge(var.tags, {
    Name = "${var.project_name}-private-rt"
  })
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private_rt.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private_rt.id
}

resource "aws_security_group" "lambda_sg" {
  name        = "${var.project_name}-lambda-sg"
  description = "Security group for private VPC GenAI Lambda functions"
  vpc_id      = aws_vpc.genai_vpc.id

  egress {
    description = "Allow HTTPS egress to private VPC endpoints and S3 gateway"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "vpce_sg" {
  name        = "${var.project_name}-vpce-sg"
  description = "Security group for OpenSearch Serverless and AWS PrivateLink VPC Endpoints"
  vpc_id      = aws_vpc.genai_vpc.id

  ingress {
    description     = "Allow HTTPS strictly from GenAI Lambda execution security group"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda_sg.id]
  }

  tags = var.tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.genai_vpc.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private_rt.id]
  tags              = var.tags
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = aws_vpc.genai_vpc.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpce_sg.id]
  private_dns_enabled = true
  tags                = var.tags
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.genai_vpc.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpce_sg.id]
  private_dns_enabled = true
  tags                = var.tags
}

# ==============================================================================
# 3. Document Ingestion Storage (S3 with Tenant Prefix Enforcement)
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
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "knowledge_documents" {
  bucket = aws_s3_bucket.knowledge_documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tenant_prefix_isolation" {
  bucket = aws_s3_bucket.knowledge_documents.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonTLSRequests"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.knowledge_documents.arn,
          "${aws_s3_bucket.knowledge_documents.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
      {
        # Tenant-tagged principals may only write under their own tenants/<tenant_id>/ prefix.
        Sid       = "DenyTenantPrincipalUploadsOutsideOwnPrefix"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        NotResource = [
          "${aws_s3_bucket.knowledge_documents.arn}/tenants/$${aws:PrincipalTag/tenant_id}/*"
        ]
        Condition = {
          Null = {
            "aws:PrincipalTag/tenant_id" = "false"
          }
        }
      },
      {
        # Untagged principals may upload only if listed as document administrators.
        Sid       = "DenyUntaggedNonAdminUploads"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = ["${aws_s3_bucket.knowledge_documents.arn}/*"]
        Condition = {
          Null = {
            "aws:PrincipalTag/tenant_id" = "true"
          }
          ArnNotLike = {
            "aws:PrincipalArn" = concat(
              ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"],
              var.document_admin_principal_arns
            )
          }
        }
      }
    ]
  })
}

# ==============================================================================
# 4. Separated Least-Privilege IAM Execution Roles
# ==============================================================================
locals {
  # Cross-Region inference profiles (us./eu./global. ...) need IAM on BOTH the profile
  # ARN and the underlying foundation model in every Region the profile can route to.
  inference_profile_prefix_re = "^(us|eu|apac|au|ca|jp|in|global)\\."
  claude_invoke_arns = flatten([
    for model_id in distinct([var.primary_claude_model_id, var.fallback_claude_model_id]) :
    can(regex(local.inference_profile_prefix_re, model_id)) ? tolist([
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${model_id}",
      "arn:aws:bedrock:*::foundation-model/${replace(model_id, "/${local.inference_profile_prefix_re}/", "")}",
      ]) : tolist([
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${model_id}",
    ])
  ])

  assume_lambda_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })
}

# 4a. Orchestrator Query Role (Bedrock Claude/Titan + Read-Only AOSS; ZERO S3 access)
resource "aws_iam_role" "orchestrator_exec" {
  name               = "${var.project_name}-orchestrator-role"
  assume_role_policy = local.assume_lambda_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "orchestrator_policy" {
  name = "${var.project_name}-orchestrator-least-privilege"
  role = aws_iam_role.orchestrator_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockClaudeAndQueryEmbeddingInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:ApplyGuardrail"
        ]
        Resource = concat(
          local.claude_invoke_arns,
          [
            "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.embedding_model_id}",
            module.bedrock_agent.guardrail_arn
          ]
        )
      },
      {
        Sid    = "OpenSearchServerlessCollectionEndpointAccess"
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll"
        ]
        Resource = [module.opensearch_serverless.collection_arn]
      },
      {
        Sid    = "VerifyTenantContextHMACSecret"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [aws_secretsmanager_secret.tenant_context_hmac.arn]
      },
      {
        Sid    = "KMSDecryptOnly"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = [module.security.kms_key_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "orchestrator_vpc_access" {
  role       = aws_iam_role.orchestrator_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# 4b. Ingestion Worker Role (Titan Embeddings + S3 Tenant Prefix Read + AOSS Index/Write; ZERO Claude access)
resource "aws_iam_role" "ingestion_exec" {
  name               = "${var.project_name}-ingestion-role"
  assume_role_policy = local.assume_lambda_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "ingestion_policy" {
  name = "${var.project_name}-ingestion-least-privilege"
  role = aws_iam_role.ingestion_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockTitanEmbeddingOnly"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.embedding_model_id}"
        ]
      },
      {
        Sid    = "S3ReadTenantDocumentsOnly"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.knowledge_documents.arn}/tenants/*"
        ]
      },
      {
        Sid    = "OpenSearchServerlessCollectionEndpointAccess"
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll"
        ]
        Resource = [module.opensearch_serverless.collection_arn]
      },
      {
        Sid    = "KMSDecryptAndGenerateDataKey"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = [module.security.kms_key_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ingestion_vpc_access" {
  role       = aws_iam_role.ingestion_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# 4c. Ingress Identity Gatekeeper Role (Seals JWT Tenant Context & Starts Step Functions)
resource "aws_iam_role" "auth_gatekeeper_exec" {
  name               = "${var.project_name}-auth-gatekeeper-role"
  assume_role_policy = local.assume_lambda_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "auth_gatekeeper_policy" {
  name = "${var.project_name}-auth-gatekeeper-least-privilege"
  role = aws_iam_role.auth_gatekeeper_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageAgentStateMachineExecution"
        Effect = "Allow"
        Action = [
          "states:StartExecution",
          "states:DescribeExecution"
        ]
        Resource = [
          module.orchestrator_step_functions.state_machine_arn,
          "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:execution:${module.orchestrator_step_functions.state_machine_name}:*"
        ]
      },
      {
        Sid    = "ManageTenantContextHMACSecret"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue"
        ]
        Resource = [aws_secretsmanager_secret.tenant_context_hmac.arn]
      },
      {
        Sid    = "KMSDecryptAndGenerateSecret"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [module.security.kms_key_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "auth_gatekeeper_basic" {
  role       = aws_iam_role.auth_gatekeeper_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ==============================================================================
# 5. OpenSearch Serverless Vector Collection (CMK Encrypted + Private VPCE)
# ==============================================================================
module "opensearch_serverless" {
  source                  = "./modules/opensearch_serverless"
  project_name            = var.project_name
  environment             = var.environment
  kms_key_arn             = module.security.kms_key_arn
  vpc_id                  = aws_vpc.genai_vpc.id
  private_subnet_ids      = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  vpce_security_group_ids = [aws_security_group.vpce_sg.id]
  orchestrator_role_arn   = aws_iam_role.orchestrator_exec.arn
  ingestion_role_arn      = aws_iam_role.ingestion_exec.arn
  tags                    = var.tags
}

# ==============================================================================
# 6. Bedrock Guardrails Module
# ==============================================================================
module "bedrock_agent" {
  source       = "./modules/bedrock_agent"
  project_name = var.project_name
  kms_key_arn  = module.security.kms_key_arn
  tags         = var.tags
}

# ==============================================================================
# 7. Lambda Dependency Layer & Functions (Orchestrator, Ingestion, & Gatekeeper)
# ==============================================================================

# Lambda Layer Packaging: opensearch-py, requests-aws4auth, and requests
resource "null_resource" "build_lambda_dependencies" {
  triggers = {
    requirements_hash = filemd5("${path.module}/../requirements.txt")
    script_hash       = filemd5("${path.module}/../scripts/build_layer.sh")
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../scripts/build_layer.sh"
  }
}

data "archive_file" "layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/layer.zip"

  depends_on = [null_resource.build_lambda_dependencies]
}

resource "aws_lambda_layer_version" "opensearch_dependencies" {
  filename            = data.archive_file.layer_zip.output_path
  layer_name          = "${var.project_name}-opensearch-dependencies"
  compatible_runtimes = ["python3.11"]
  source_code_hash    = data.archive_file.layer_zip.output_base64sha256
  description         = "Runtime dependencies: opensearch-py 2.8.0, requests-aws4auth 1.3.1, requests"
}

data "archive_file" "runtime_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/build/runtime.zip"
}

resource "aws_lambda_function" "orchestrator" {
  filename         = data.archive_file.runtime_zip.output_path
  function_name    = "${var.project_name}-orchestrator"
  role             = aws_iam_role.orchestrator_exec.arn
  handler          = "orchestrator.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 1024
  source_code_hash = data.archive_file.runtime_zip.output_base64sha256
  layers           = [aws_lambda_layer_version.opensearch_dependencies.arn]

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      PRIMARY_CLAUDE_MODEL_ID   = var.primary_claude_model_id
      FALLBACK_CLAUDE_MODEL_ID  = var.fallback_claude_model_id
      EMBEDDING_MODEL_ID        = var.embedding_model_id
      BEDROCK_GUARDRAIL_ID      = element(split("/", module.bedrock_agent.guardrail_arn), length(split("/", module.bedrock_agent.guardrail_arn)) - 1)
      BEDROCK_GUARDRAIL_VER     = module.bedrock_agent.guardrail_version
      OPENSEARCH_ENDPOINT       = module.opensearch_serverless.collection_endpoint
      TENANT_CONTEXT_SECRET_ARN = aws_secretsmanager_secret.tenant_context_hmac.arn
      MODEL_PRICING_JSON        = jsonencode(var.model_pricing_usd_per_1k_tokens)
      POWERTOOLS_SERVICE_NAME   = "claude-orchestrator"
      LOG_LEVEL                 = "INFO"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_lambda_function" "ingestion" {
  filename         = data.archive_file.runtime_zip.output_path
  function_name    = "${var.project_name}-ingestion"
  role             = aws_iam_role.ingestion_exec.arn
  handler          = "ingestion.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 180
  memory_size      = 512
  source_code_hash = data.archive_file.runtime_zip.output_base64sha256
  layers           = [aws_lambda_layer_version.opensearch_dependencies.arn]

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

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

# Declarative Vector Index Bootstrapper (Ensures 1,024-dim HNSW knn_vector mapping exists)
resource "aws_lambda_invocation" "bootstrap_vector_index" {
  function_name = aws_lambda_function.ingestion.function_name

  input = jsonencode({
    action = "BOOTSTRAP_INDEX"
  })

  depends_on = [
    module.opensearch_serverless,
    aws_lambda_layer_version.opensearch_dependencies
  ]
}

# ==============================================================================
# 8. S3 Document Ingestion Notification (Scoped to `tenants/` prefix)
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
    filter_prefix       = "tenants/"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_ingestion,
    aws_lambda_invocation.bootstrap_vector_index
  ]
}

# ==============================================================================
# 9. Agentic Step Functions State Machine
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
# 10. Tenant Identity Layer (Cognito User Pool + API Gateway JWT Authorizer)
# ==============================================================================
resource "aws_cognito_user_pool" "tenant_identity_pool" {
  name = "${var.project_name}-tenant-pool"

  # Tenant membership is assigned by an administrator, never self-declared. With self
  # sign-up enabled, any caller could SignUp with an arbitrary custom:tenant_id.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  schema {
    name                = "tenant_id"
    attribute_data_type = "String"
    mutable             = false
    required            = false
    string_attribute_constraints {
      min_length = 3
      max_length = 64
    }
  }

  tags = var.tags
}

resource "aws_cognito_user_pool_client" "api_client" {
  name                                 = "${var.project_name}-api-client"
  user_pool_id                         = aws_cognito_user_pool.tenant_identity_pool.id
  generate_secret                      = false
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  allowed_oauth_flows_user_pool_client = false

  # Clients may read the tenant claim but never write it (SignUp / UpdateUserAttributes).
  read_attributes  = ["email", "email_verified", "name", "custom:tenant_id"]
  write_attributes = ["email", "name"]
}

resource "aws_lambda_function" "auth_gatekeeper" {
  filename         = data.archive_file.runtime_zip.output_path
  function_name    = "${var.project_name}-auth-gatekeeper"
  role             = aws_iam_role.auth_gatekeeper_exec.arn
  handler          = "auth.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 256
  source_code_hash = data.archive_file.runtime_zip.output_base64sha256

  environment {
    variables = {
      STATE_MACHINE_ARN         = module.orchestrator_step_functions.state_machine_arn
      TENANT_CONTEXT_SECRET_ARN = aws_secretsmanager_secret.tenant_context_hmac.arn
      POWERTOOLS_SERVICE_NAME   = "claude-auth-gatekeeper"
      LOG_LEVEL                 = "INFO"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_apigatewayv2_api" "agent_api" {
  name          = "${var.project_name}-http-api"
  protocol_type = "HTTP"
  description   = "Authenticated multi-tenant ingress API for Enterprise Claude Agentic Workflows"
  tags          = var.tags
}

resource "aws_apigatewayv2_authorizer" "cognito_jwt" {
  api_id           = aws_apigatewayv2_api.agent_api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.project_name}-cognito-jwt-authorizer"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.api_client.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.tenant_identity_pool.id}"
  }
}

resource "aws_apigatewayv2_integration" "gatekeeper_integration" {
  api_id                 = aws_apigatewayv2_api.agent_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.auth_gatekeeper.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "start_execution_route" {
  api_id             = aws_apigatewayv2_api.agent_api.id
  route_key          = "POST /v1/agent/executions"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
  target             = "integrations/${aws_apigatewayv2_integration.gatekeeper_integration.id}"
}

resource "aws_apigatewayv2_route" "get_execution_route" {
  api_id             = aws_apigatewayv2_api.agent_api.id
  route_key          = "GET /v1/agent/executions/{execution_id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
  target             = "integrations/${aws_apigatewayv2_integration.gatekeeper_integration.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.agent_api.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "allow_apigw_gatekeeper" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth_gatekeeper.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.agent_api.execution_arn}/*/*"
}

# ==============================================================================
# 11. Observability & CloudWatch Dashboards
# ==============================================================================
module "observability" {
  source             = "./modules/observability_adot"
  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  state_machine_arn  = module.orchestrator_step_functions.state_machine_arn
  primary_model_id   = var.primary_claude_model_id
  fallback_model_id  = var.fallback_claude_model_id
  kms_key_arn        = module.security.kms_key_arn
  tags               = var.tags
}

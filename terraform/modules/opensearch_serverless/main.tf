data "aws_caller_identity" "current" {}

# OpenSearch Serverless Security Encryption Policy
resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.project_name}-enc"
  type = "encryption"

  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource = [
          "collection/${var.project_name}-kb"
        ]
      }
    ]
    AWSOwnedKey = true
  })
}

# OpenSearch Serverless Network Policy (VPC/Public with strict auth)
resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.project_name}-net"
  type = "network"

  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource = [
            "collection/${var.project_name}-kb"
          ]
        },
        {
          ResourceType = "dashboard"
          Resource = [
            "collection/${var.project_name}-kb"
          ]
        }
      ]
      AllowFromPublic = true
    }
  ])
}

# OpenSearch Serverless Vector Collection
resource "aws_opensearchserverless_collection" "knowledge_base" {
  name        = "${var.project_name}-kb"
  description = "Authoritative enterprise vector search knowledge base for Claude agent retrieval"
  type        = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network
  ]

  tags = merge(var.tags, {
    Name = "${var.project_name}-kb"
  })
}

# OpenSearch Serverless Data Access Policy
resource "aws_opensearchserverless_access_policy" "data_access" {
  name        = "${var.project_name}-access"
  type        = "data"
  description = "Allows Lambda ingest and agent orchestrator to perform vector indexing and hybrid search"

  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "index"
          Resource = [
            "index/${var.project_name}-kb/*"
          ]
          Permission = [
            "aoss:CreateIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:ReadDocument",
            "aoss:WriteDocument"
          ]
        },
        {
          ResourceType = "collection"
          Resource = [
            "collection/${var.project_name}-kb"
          ]
          Permission = [
            "aoss:DescribeCollectionItems",
            "aoss:CreateCollectionItems",
            "aoss:UpdateCollectionItems"
          ]
        }
      ]
      Principal = [
        var.lambda_execution_role_arn,
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      ]
    }
  ])
}

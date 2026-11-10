# ==============================================================================
# OpenSearch Serverless Interface VPC Endpoint (Private Network Isolation)
# ==============================================================================
resource "aws_opensearchserverless_vpc_endpoint" "aoss_vpce" {
  name               = "${var.project_name}-vpce"
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
  security_group_ids = var.vpce_security_group_ids
}

# ==============================================================================
# OpenSearch Serverless Encryption Policy (Customer Managed KMS Key)
# ==============================================================================
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
    AWSOwnedKey = false
    KmsARN      = var.kms_key_arn
  })
}

# ==============================================================================
# OpenSearch Serverless Network Policy (Strictly Private via VPC Endpoint)
# ==============================================================================
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
      AllowFromPublic = false
      SourceVPCEs = [
        aws_opensearchserverless_vpc_endpoint.aoss_vpce.id
      ]
    }
  ])
}

# ==============================================================================
# OpenSearch Serverless Vector Collection
# ==============================================================================
resource "aws_opensearchserverless_collection" "knowledge_base" {
  name        = "${var.project_name}-kb"
  description = "Authoritative enterprise vector search knowledge base (1,024-dim HNSW + BM25)"
  type        = "VECTORSEARCH"

  # ENABLED keeps a standby copy in a second AZ (2-OCU billing minimum). DISABLED halves
  # the minimum for dev/test at the cost of availability. Changing it replaces the collection.
  standby_replicas = var.standby_replicas

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network
  ]

  tags = merge(var.tags, {
    Name = "${var.project_name}-kb"
  })
}

# ==============================================================================
# OpenSearch Serverless Data Access Policy (Separated Read vs. Write Principals)
# ==============================================================================
resource "aws_opensearchserverless_access_policy" "data_access" {
  name        = "${var.project_name}-access"
  type        = "data"
  description = "Least-privilege separation: Ingestion role writes/creates index; Orchestrator role has read-only search access"

  policy = jsonencode([
    {
      Description = "Ingestion Worker: Index creation and document indexing permissions"
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
        var.ingestion_role_arn
      ]
    },
    {
      Description = "Orchestrator Agent: Strictly read-only hybrid k-NN and BM25 search permissions"
      Rules = [
        {
          ResourceType = "index"
          Resource = [
            "index/${var.project_name}-kb/*"
          ]
          Permission = [
            "aoss:DescribeIndex",
            "aoss:ReadDocument"
          ]
        },
        {
          ResourceType = "collection"
          Resource = [
            "collection/${var.project_name}-kb"
          ]
          Permission = [
            "aoss:DescribeCollectionItems"
          ]
        }
      ]
      Principal = [
        var.orchestrator_role_arn
      ]
    }
  ])
}

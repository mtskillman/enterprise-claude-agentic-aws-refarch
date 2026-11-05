output "collection_arn" {
  value       = aws_opensearchserverless_collection.knowledge_base.arn
  description = "ARN of the OpenSearch Serverless vector collection."
}

output "collection_endpoint" {
  value       = aws_opensearchserverless_collection.knowledge_base.collection_endpoint
  description = "HTTPS endpoint of the OpenSearch Serverless vector collection."
}

output "collection_id" {
  value       = aws_opensearchserverless_collection.knowledge_base.id
  description = "Unique collection ID."
}

output "vpc_endpoint_id" {
  value       = aws_opensearchserverless_vpc_endpoint.aoss_vpce.id
  description = "ID of the private OpenSearch Serverless Interface VPC Endpoint."
}

output "index_mapping_json" {
  value       = file("${path.module}/index_mapping.json")
  description = "Explicit 1,024-dimensional HNSW k-NN index schema definition."
}

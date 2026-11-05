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

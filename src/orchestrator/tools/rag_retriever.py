"""OpenSearch Serverless Hybrid Vector & Lexical Retrieval Tool."""

from __future__ import annotations

import json
from typing import Any, Dict

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from ...shared.config import AppConfig
from ...shared.opensearch_index import EMBEDDING_DIMENSIONS
from ...shared.tenant_context import VerifiedTenantContext
from .base import BaseTool


class OpenSearchRAGRetrieverTool(BaseTool):
    """Retrieves authoritative enterprise documents using hybrid vector/keyword search."""

    name = "enterprise_knowledge_search"
    description = (
        "Search the enterprise authoritative knowledge base using semantic and keyword matching. "
        "Use this tool whenever the user asks for policies, architecture blueprints, or organizational data."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query to locate relevant documentation.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of top document passages to return (default: 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self.bedrock_runtime = boto3.client(
            "bedrock-runtime", region_name=self.config.aws_region
        )
        self._init_opensearch_client()

    def _init_opensearch_client(self) -> None:
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(
            credentials, self.config.aws_region, "aoss"
        )
        endpoint = self.config.opensearch_endpoint.replace("https://", "").rstrip("/")
        self.client = OpenSearch(
            hosts=[{"host": endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=10,
        )

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate 1,024-dimension vector embedding via Amazon Titan Text Embeddings v2."""
        payload = json.dumps(
            {
                "inputText": text,
                "dimensions": EMBEDDING_DIMENSIONS,
                "normalize": True,
            }
        )
        response = self.bedrock_runtime.invoke_model(
            modelId=self.config.embedding_model_id,
            contentType="application/json",
            accept="application/json",
            body=payload,
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def execute(self, arguments: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        # Enforce strict tenant_id validation (never fall back to a shared default)
        VerifiedTenantContext.validate_tenant_id_format(tenant_id)

        query_text = arguments["query"]
        top_k = int(arguments.get("top_k", 5))
        query_vector = self._generate_embedding(query_text)

        tenant_filter = {"term": {"tenant_id": tenant_id}}

        # Hybrid query: HNSW k-NN pre-filtered vector search + BM25 lexical search
        # with mandatory tenant_id partition isolation and minimum_should_match=1.
        search_query = {
            "size": top_k,
            "query": {
                "bool": {
                    "filter": [tenant_filter],
                    "should": [
                        {
                            "knn": {
                                "embedding": {
                                    "vector": query_vector,
                                    "k": top_k,
                                    "filter": tenant_filter,
                                }
                            }
                        },
                        {
                            "multi_match": {
                                "query": query_text,
                                "fields": ["content^2", "title"],
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
        }

        try:
            response = self.client.search(
                body=search_query, index=self.config.opensearch_index_name
            )
            hits = response.get("hits", {}).get("hits", [])
            passages = [
                {
                    "title": hit["_source"].get("title", "Untitled"),
                    "content": hit["_source"].get("content", ""),
                    "score": hit["_score"],
                    "document_id": hit["_source"].get("document_id"),
                }
                for hit in hits
            ]
            return {"status": "success", "results_count": len(passages), "passages": passages}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "passages": []}

"""OpenSearch Serverless Vector Index Schema & Bootstrapper.

Defines the authoritative k-NN vector index mapping required by Amazon OpenSearch
Serverless (`VECTORSEARCH` collection) for hybrid BM25 + 1,024-dimensional HNSW
vector retrieval using Amazon Titan Text Embeddings v2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from opensearchpy import OpenSearch
from opensearchpy.exceptions import RequestError

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1024

KNOWLEDGE_BASE_INDEX_BODY: Dict[str, Any] = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 512,
        }
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "document_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "standard",
                "fields": {"raw": {"type": "keyword"}},
            },
            "content": {
                "type": "text",
                "analyzer": "standard",
            },
            "s3_uri": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIMENSIONS,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "cosinesimil",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16,
                    },
                },
            },
        },
    },
}


def ensure_vector_index_exists(os_client: OpenSearch, index_name: str) -> bool:
    """Idempotently create the k-NN vector index with explicit HNSW mapping if absent.

    Returns True if the index was newly created, or False if it already existed.
    """
    if os_client.indices.exists(index=index_name):
        return False

    try:
        logger.info(
            "Creating OpenSearch Serverless vector index '%s' (dimension=%d, engine=faiss/hnsw)",
            index_name,
            EMBEDDING_DIMENSIONS,
        )
        os_client.indices.create(index=index_name, body=KNOWLEDGE_BASE_INDEX_BODY)
        return True
    except RequestError as exc:
        # Handle benign race condition if another concurrent invocation created the index
        if exc.error in ("resource_already_exists_exception", "index_already_exists_exception"):
            logger.info("Vector index '%s' already created concurrently.", index_name)
            return False
        raise

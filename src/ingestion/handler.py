"""S3 Document Upload Event Ingestion & Vector Index Bootstrapper Lambda Handler.

Supports two execution modes:
1. S3 Event Notification (`Records`):
   - Enforces deterministic tenant binding from the IAM-governed S3 prefix
     `tenants/<tenant_id>/<document_key>` via `extract_verified_tenant_from_s3_key`.
   - Ensures the OpenSearch Serverless k-NN vector index mapping exists.
   - Chunks documents, generates 1,024-dim Amazon Titan Text Embeddings v2,
     and indexes documents into OpenSearch Serverless.
2. Index Bootstrap (`{"action": "BOOTSTRAP_INDEX"}`):
   - Idempotently creates the explicit `knn_vector` HNSW index schema during IaC deployment.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Dict

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import NotFoundError

from shared.config import AppConfig
from shared.opensearch_index import EMBEDDING_DIMENSIONS, ensure_vector_index_exists
from shared.tenant_context import extract_verified_tenant_from_s3_key
from .chunker import TextChunker

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    config = AppConfig()
    s3_client = boto3.client("s3", region_name=config.aws_region)
    bedrock_client = boto3.client("bedrock-runtime", region_name=config.aws_region)

    # Initialize OpenSearch Serverless client
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, config.aws_region, "aoss")
    endpoint = config.opensearch_endpoint.replace("https://", "").rstrip("/")
    os_client = OpenSearch(
        hosts=[{"host": endpoint, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=15,
    )

    # Ensure explicit k-NN vector index mapping exists before any document writes
    created = ensure_vector_index_exists(os_client, config.opensearch_index_name)
    if event.get("action") == "BOOTSTRAP_INDEX":
        return {
            "status": "INDEX_BOOTSTRAPPED",
            "index_name": config.opensearch_index_name,
            "newly_created": created,
            "dimensions": EMBEDDING_DIMENSIONS,
        }

    chunker = TextChunker(chunk_size_words=350, overlap_words=50)
    indexed_count = 0

    records = event.get("Records", [])
    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        logger.info("Processing S3 object s3://%s/%s", bucket, key)
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        metadata = obj.get("Metadata", {})

        # Deterministically bind tenant_id from the IAM-governed S3 key prefix `tenants/<tenant_id>/...`
        tenant_id = extract_verified_tenant_from_s3_key(key, metadata)

        content_text = obj["Body"].read().decode("utf-8", errors="ignore")
        title = metadata.get("title", key.split("/")[-1])

        s3_uri = f"s3://{bucket}/{key}"

        # VECTORSEARCH collections assign document IDs server-side, so re-uploads cannot
        # overwrite by ID. Remove this object's previous chunks before re-indexing it.
        _delete_existing_chunks(os_client, config.opensearch_index_name, tenant_id, s3_uri)

        chunks = chunker.chunk(content_text)
        for idx, chunk_text in enumerate(chunks):
            payload = json.dumps(
                {
                    "inputText": chunk_text,
                    "dimensions": EMBEDDING_DIMENSIONS,
                    "normalize": True,
                }
            )
            embed_res = bedrock_client.invoke_model(
                modelId=config.embedding_model_id,
                contentType="application/json",
                accept="application/json",
                body=payload,
            )
            embedding = json.loads(embed_res["body"].read())["embedding"]

            # Logical chunk identifier (stored as a field, not used as the OpenSearch _id).
            doc = {
                "document_id": f"{tenant_id}:{key}#{idx}",
                "title": title,
                "content": chunk_text,
                "embedding": embedding,
                "tenant_id": tenant_id,
                "s3_uri": s3_uri,
                "chunk_index": idx,
            }

            os_client.index(index=config.opensearch_index_name, body=doc)
            indexed_count += 1

    return {"status": "SUCCESS", "indexed_chunks": indexed_count}


def _delete_existing_chunks(os_client: OpenSearch, index_name: str, tenant_id: str, s3_uri: str) -> int:
    """Delete previously indexed chunks of one S3 object (by server-generated _id)."""
    resp = os_client.search(
        index=index_name,
        body={
            "size": 10000,
            "_source": False,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"s3_uri": s3_uri}},
                    ]
                }
            },
        },
    )
    deleted = 0
    for hit in resp.get("hits", {}).get("hits", []):
        try:
            os_client.delete(index=index_name, id=hit["_id"])
            deleted += 1
        except NotFoundError:
            pass
    if deleted:
        logger.info("Removed %d stale chunks for %s", deleted, s3_uri)
    return deleted

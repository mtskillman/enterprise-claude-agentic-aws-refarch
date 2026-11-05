"""S3 Document Upload Event Ingestion Lambda Handler.

Triggered via S3 ObjectCreated / EventBridge:
1. Downloads PDF/Markdown/TXT document from S3.
2. Chunks document into overlapping passages.
3. Generates embeddings using Amazon Titan Text Embeddings v2.
4. Indexes documents into Amazon OpenSearch Serverless vector index.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Dict

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from ..shared.config import AppConfig
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

    chunker = TextChunker(chunk_size_words=350, overlap_words=50)
    indexed_count = 0

    records = event.get("Records", [])
    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        logger.info("Processing S3 object s3://%s/%s", bucket, key)
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        content_text = obj["Body"].read().decode("utf-8", errors="ignore")
        metadata = obj.get("Metadata", {})
        tenant_id = metadata.get("tenant-id", "default")
        title = metadata.get("title", key.split("/")[-1])

        chunks = chunker.chunk(content_text)
        for idx, chunk_text in enumerate(chunks):
            # Generate embedding
            payload = json.dumps({"inputText": chunk_text, "dimensions": 1024, "normalize": True})
            embed_res = bedrock_client.invoke_model(
                modelId=config.embedding_model_id,
                contentType="application/json",
                accept="application/json",
                body=payload,
            )
            embedding = json.loads(embed_res["body"].read())["embedding"]

            doc = {
                "document_id": f"{key}#{idx}",
                "title": title,
                "content": chunk_text,
                "embedding": embedding,
                "tenant_id": tenant_id,
                "s3_uri": f"s3://{bucket}/{key}",
            }

            os_client.index(
                index=config.opensearch_index_name,
                id=f"{key}#{idx}",
                body=doc,
                refresh=False,
            )
            indexed_count += 1

    return {"status": "SUCCESS", "indexed_chunks": indexed_count}

"""Application configuration loaded from AWS Lambda environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    environment: str = os.getenv("ENVIRONMENT", "prod")
    primary_model_id: str = os.getenv(
        "PRIMARY_CLAUDE_MODEL_ID",
        os.getenv("PRIMARY_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
    )
    fallback_model_id: str = os.getenv(
        "FALLBACK_CLAUDE_MODEL_ID",
        os.getenv("FALLBACK_MODEL_ID", "anthropic.claude-3-5-haiku-20241022-v1:0"),
    )
    embedding_model_id: str = os.getenv(
        "EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
    )
    bedrock_guardrail_id: str = os.getenv("BEDROCK_GUARDRAIL_ID", "")
    bedrock_guardrail_version: str = os.getenv("BEDROCK_GUARDRAIL_VER", "1")
    opensearch_endpoint: str = os.getenv("OPENSEARCH_ENDPOINT", "")
    opensearch_index_name: str = os.getenv(
        "OPENSEARCH_INDEX_NAME", "enterprise-knowledge-base"
    )
    tenant_context_secret_arn: str = os.getenv("TENANT_CONTEXT_SECRET_ARN", "")
    state_machine_arn: str = os.getenv("STATE_MACHINE_ARN", "")
    max_agent_iterations: int = int(os.getenv("MAX_AGENT_ITERATIONS", "10"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))

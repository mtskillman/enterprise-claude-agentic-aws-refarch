"""Application configuration loaded from AWS Lambda environment variables."""

import os
from dataclasses import dataclass
from typing import Optional


def _optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


@dataclass(frozen=True)
class AppConfig:
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    environment: str = os.getenv("ENVIRONMENT", "prod")
    # Cross-Region inference profile IDs (current Claude models are not invocable
    # on-demand by base foundation-model ID).
    primary_model_id: str = os.getenv(
        "PRIMARY_CLAUDE_MODEL_ID",
        os.getenv("PRIMARY_MODEL_ID", "us.anthropic.claude-sonnet-5"),
    )
    fallback_model_id: str = os.getenv(
        "FALLBACK_CLAUDE_MODEL_ID",
        os.getenv("FALLBACK_MODEL_ID", "us.anthropic.claude-haiku-5-5"),
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
    temperature: Optional[float] = _optional_float("TEMPERATURE")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))

"""OpenTelemetry GenAI Semantic Conventions & Cost Telemetry Helper.

Instruments Anthropic Claude model invocations on Amazon Bedrock with
distributed tracing, latency profiling, and token cost attribution.
"""

from __future__ import annotations

import os
from typing import Any, Dict


class GenAITelemetry:
    """Telemetry helper adhering to OpenTelemetry GenAI semantic conventions."""

    PRICING = {
        # Per 1,000 tokens (USD)
        "anthropic.claude-3-5-sonnet-20241022-v2:0": {
            "input": 0.003,
            "output": 0.015,
        },
        "anthropic.claude-3-5-haiku-20241022-v1:0": {
            "input": 0.0008,
            "output": 0.004,
        },
        "amazon.titan-embed-text-v2:0": {
            "input": 0.00002,
            "output": 0.0,
        },
    }

    @classmethod
    def calculate_cost(
        cls, model_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculate estimated cost in USD based on published AWS Bedrock pricing."""
        rates = cls.PRICING.get(
            model_id, {"input": 0.003, "output": 0.015}
        )
        input_cost = (input_tokens / 1000.0) * rates["input"]
        output_cost = (output_tokens / 1000.0) * rates["output"]
        return round(input_cost + output_cost, 6)

    @classmethod
    def create_span_attributes(
        cls,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        tenant_id: str = "default",
        tool_name: str | None = None,
    ) -> Dict[str, Any]:
        """Construct standard OpenTelemetry attributes for GenAI operations."""
        cost = cls.calculate_cost(model_id, input_tokens, output_tokens)
        attrs = {
            "gen_ai.system": "aws.bedrock",
            "gen_ai.request.model": model_id,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.total_tokens": input_tokens + output_tokens,
            "gen_ai.usage.estimated_cost_usd": cost,
            "tenant.id": tenant_id,
            "service.name": os.getenv("SERVICE_NAME", "agentic-orchestrator"),
            "environment": os.getenv("ENVIRONMENT", "production"),
        }
        if tool_name:
            attrs["gen_ai.tool.name"] = tool_name
        return attrs

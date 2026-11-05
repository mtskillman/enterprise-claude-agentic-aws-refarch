"""OpenTelemetry GenAI Semantic Conventions & CloudWatch EMF Cost Telemetry.

Instruments Anthropic Claude model invocations on Amazon Bedrock with
OpenTelemetry-compliant distributed tracing, latency profiling, and real-time
CloudWatch Embedded Metric Format (EMF) multi-tenant cost attribution.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

logger = logging.getLogger()


class GenAITelemetry:
    """Telemetry and FinOps helper adhering to OpenTelemetry GenAI semantic conventions."""

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

    EMF_NAMESPACE = "EnterpriseClaude/AgenticWorkflows"

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
        tool_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct standard OpenTelemetry attributes for GenAI operations."""
        cost = cls.calculate_cost(model_id, input_tokens, output_tokens)
        attrs: Dict[str, Any] = {
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

    @classmethod
    def emit_turn_telemetry(
        cls,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        tenant_id: str = "default",
        latency_ms: float = 0.0,
        tool_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Emit real-time CloudWatch EMF metrics and return OpenTelemetry attributes."""
        cost = cls.calculate_cost(model_id, input_tokens, output_tokens)
        attrs = cls.create_span_attributes(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tenant_id=tenant_id,
            tool_name=tool_name,
        )

        # Emit CloudWatch Embedded Metric Format (EMF)
        # CloudWatch extracts these high-cardinality multi-tenant metrics with zero API latency.
        now_ms = int(time.time() * 1000)
        emf_payload = {
            "_aws": {
                "Timestamp": now_ms,
                "CloudWatchMetrics": [
                    {
                        "Namespace": cls.EMF_NAMESPACE,
                        "Dimensions": [
                            ["TenantId"],
                            ["ModelId"],
                            ["TenantId", "ModelId"],
                        ],
                        "Metrics": [
                            {"Name": "EstimatedCostUSD", "Unit": "None"},
                            {"Name": "InputTokens", "Unit": "Count"},
                            {"Name": "OutputTokens", "Unit": "Count"},
                            {"Name": "TotalTokens", "Unit": "Count"},
                            {"Name": "TurnLatencyMs", "Unit": "Milliseconds"},
                        ],
                    }
                ],
            },
            "TenantId": tenant_id,
            "ModelId": model_id,
            "EstimatedCostUSD": cost,
            "InputTokens": input_tokens,
            "OutputTokens": output_tokens,
            "TotalTokens": input_tokens + output_tokens,
            "TurnLatencyMs": round(latency_ms, 2),
        }

        # Print raw EMF JSON directly to stdout for CloudWatch agent extraction
        sys.stdout.write(json.dumps(emf_payload) + "\n")
        sys.stdout.flush()

        logger.info(
            "Emitted GenAI Telemetry & FinOps: tenant=%s model=%s cost=$%s tokens=%s latency=%.1fms",
            tenant_id,
            model_id,
            cost,
            input_tokens + output_tokens,
            latency_ms,
        )

        return attrs

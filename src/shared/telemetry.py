"""OpenTelemetry GenAI Semantic Conventions & CloudWatch EMF Cost Telemetry.

Instruments Anthropic Claude model invocations on Amazon Bedrock with
real OpenTelemetry distributed tracing spans, latency profiling, and real-time
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

# Attempt to configure actual OpenTelemetry TracerProvider
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Status, StatusCode

    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        # In Lambda/container environments without OTLP collector, ConsoleSpanExporter emits structured span logs
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)

    _tracer = trace.get_tracer("enterprise-claude-agentic-aws-refarch")
    _OTEL_AVAILABLE = True
except Exception as err:
    logger.debug("OpenTelemetry SDK not active in local environment: %s", err)
    _tracer = None


def _load_pricing() -> Dict[str, Dict[str, float]]:
    """Load per-1,000-token USD rates from MODEL_PRICING_JSON.

    Bedrock pricing varies by model, Region, inference profile scope, and service
    tier, so rates are supplied by the operator (Terraform `model_pricing_usd_per_1k_tokens`)
    rather than hardcoded. Format: {"<model or profile id>": {"input": 0.0, "output": 0.0}}.
    """
    raw = os.getenv("MODEL_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("MODEL_PRICING_JSON is not valid JSON; cost attribution disabled.")
        return {}


class GenAITelemetry:
    """Telemetry and FinOps helper adhering to OpenTelemetry GenAI semantic conventions."""

    EMF_NAMESPACE = "EnterpriseClaude/AgenticWorkflows"

    PRICING: Dict[str, Dict[str, float]] = _load_pricing()

    @classmethod
    def calculate_cost(
        cls, model_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate cost in USD from operator-configured rates; 0.0 if the model is unpriced."""
        rates = cls.PRICING.get(model_id)
        if rates is None:
            logger.warning("No pricing configured for model '%s'; reporting EstimatedCostUSD=0.", model_id)
            return 0.0
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
        """Emit real OpenTelemetry span and real-time CloudWatch EMF metrics."""
        cost = cls.calculate_cost(model_id, input_tokens, output_tokens)
        attrs = cls.create_span_attributes(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tenant_id=tenant_id,
            tool_name=tool_name,
        )

        # 1. Create and end an authentic OpenTelemetry distributed trace span
        if _OTEL_AVAILABLE and _tracer is not None:
            try:
                span_name = f"gen_ai.client.turn {model_id}"
                with _tracer.start_as_current_span(span_name, attributes=attrs) as span:
                    span.set_status(Status(StatusCode.OK))
            except Exception as span_err:
                logger.warning("Failed to emit OpenTelemetry span: %s", span_err)

        # 2. Emit CloudWatch Embedded Metric Format (EMF)
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

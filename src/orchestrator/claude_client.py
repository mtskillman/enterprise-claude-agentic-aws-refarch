"""Anthropic Claude Client on Amazon Bedrock (Converse API)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from shared.config import AppConfig
from shared.telemetry import GenAITelemetry
from .tools.base import BaseTool

logger = logging.getLogger(__name__)


class ClaudeBedrockClient:
    """Wraps Anthropic Claude on Amazon Bedrock using the unified Converse API."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self.client = boto3.client(
            "bedrock-runtime", region_name=self.config.aws_region
        )

    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: List[BaseTool] | None = None,
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """Execute a single reasoning turn with Anthropic Claude on Amazon Bedrock."""
        tool_config = None
        if tools:
            tool_config = {
                "tools": [t.to_bedrock_spec() for t in tools]
            }

        params: Dict[str, Any] = {
            "modelId": self.config.primary_model_id,
            "messages": messages,
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": self.config.max_tokens,
            },
        }
        # Only send temperature when explicitly configured: current Claude models run
        # adaptive thinking by default, which constrains sampling parameters.
        if self.config.temperature is not None:
            params["inferenceConfig"]["temperature"] = self.config.temperature
        if tool_config:
            params["toolConfig"] = tool_config

        if self.config.bedrock_guardrail_id:
            params["guardrailConfig"] = {
                "guardrailIdentifier": self.config.bedrock_guardrail_id,
                "guardrailVersion": self.config.bedrock_guardrail_version,
                "trace": "enabled",
            }

        start_t = time.time()
        try:
            response = self.client.converse(**params)
        except ClientError as err:
            logger.warning(
                "Primary model %s failed, attempting fallback to %s. Reason: %s",
                self.config.primary_model_id,
                self.config.fallback_model_id,
                err,
            )
            params["modelId"] = self.config.fallback_model_id
            response = self.client.converse(**params)
        latency_ms = (time.time() - start_t) * 1000.0

        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        active_model = params["modelId"]

        telemetry_attrs = GenAITelemetry.emit_turn_telemetry(
            model_id=active_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tenant_id=tenant_id,
            latency_ms=latency_ms,
        )

        output_message = response.get("output", {}).get("message", {})
        stop_reason = response.get("stopReason")

        return {
            "model_id": active_model,
            "stop_reason": stop_reason,
            "message": output_message,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "telemetry": telemetry_attrs,
        }

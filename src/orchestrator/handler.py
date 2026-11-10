"""Step Functions Agentic Worker Lambda Handler.

Handles dual execution modes within the Step Functions state machine:
1. 'INFERENCE': Invokes Anthropic Claude on Amazon Bedrock with tools.
2. 'TOOL_EXECUTION': Dispatches tool calls requested by Claude and returns results.

Tenant Isolation:
Every invocation requires a cryptographically signed `auth_context` minted by the
ingress authorizer (`VerifiedTenantContext`). Unverified or caller-supplied
`tenant_id` overrides are rejected with `TenantIsolationError`.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Dict

import boto3

from shared.config import AppConfig
from shared.tenant_context import TenantIsolationError, VerifiedTenantContext
from .claude_client import ClaudeBedrockClient
from .tools.calculator import SafeCalculatorTool
from .tools.rag_retriever import OpenSearchRAGRetrieverTool

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SYSTEM_PROMPT = """You are an Enterprise Cloud & Platform Architecture Agent powered by Anthropic Claude.
You assist enterprise engineers with AWS architecture, security best practices, and cost governance.
When asked about enterprise architecture, policies, or standards, ALWAYS query the authoritative knowledge base first.
For mathematical calculations, compute them deterministically using the calculator tool.
Be concise, authoritative, and cite specific documentation IDs when retrieved.
"""


@functools.lru_cache(maxsize=1)
def _get_signing_secret(secret_arn: str, region: str) -> str:
    """Retrieve the HMAC signing key from AWS Secrets Manager (cached per execution environment)."""
    sm_client = boto3.client("secretsmanager", region_name=region)
    resp = sm_client.get_secret_value(SecretId=secret_arn)
    return resp["SecretString"]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    config = AppConfig()
    action = event.get("action", "INFERENCE")
    messages = event.get("messages", [])
    iteration = event.get("iteration", 0)

    # Verify cryptographic tenant identity seal minted by the Ingress Gatekeeper
    signing_secret = _get_signing_secret(
        config.tenant_context_secret_arn, config.aws_region
    )
    verified_ctx = VerifiedTenantContext.from_untrusted_dict(
        event.get("auth_context"), signing_secret=signing_secret
    )
    tenant_id = verified_ctx.tenant_id

    # Guard against any top-level payload tenant_id tampering
    if "tenant_id" in event and event["tenant_id"] != tenant_id:
        raise TenantIsolationError(
            f"Payload tenant_id '{event['tenant_id']}' does not match verified auth_context tenant '{tenant_id}'."
        )

    # Initialize tools
    rag_tool = OpenSearchRAGRetrieverTool(config=config)
    calc_tool = SafeCalculatorTool()
    tool_map = {
        rag_tool.name: rag_tool,
        calc_tool.name: calc_tool,
    }

    if action == "INFERENCE":
        client = ClaudeBedrockClient(config=config)
        turn_result = client.generate_turn(
            messages=messages,
            system_prompt=SYSTEM_PROMPT,
            tools=list(tool_map.values()),
            tenant_id=tenant_id,
        )

        message = turn_result["message"]
        messages.append(message)
        stop_reason = turn_result["stop_reason"]

        has_tool_use = stop_reason == "tool_use"
        tool_requests = []
        if has_tool_use:
            for content_block in message.get("content", []):
                if "toolUse" in content_block:
                    tool_requests.append(content_block["toolUse"])

        return {
            "status": "CONTINUE" if has_tool_use else "COMPLETE",
            "has_tool_use": has_tool_use,
            "tool_requests": tool_requests,
            "messages": messages,
            "auth_context": verified_ctx.to_dict(),
            "iteration": iteration + 1,
            "telemetry": turn_result["telemetry"],
        }

    elif action == "TOOL_EXECUTION":
        tool_requests = event.get("tool_requests", [])
        tool_results_content = []

        for req in tool_requests:
            tool_use_id = req["toolUseId"]
            tool_name = req["name"]
            tool_input = req["input"]

            tool_impl = tool_map.get(tool_name)
            if not tool_impl:
                result_payload = {"error": f"Unknown tool: {tool_name}"}
            else:
                result_payload = tool_impl.execute(tool_input, tenant_id=tenant_id)

            tool_results_content.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [{"json": result_payload}],
                    }
                }
            )

        # Append tool results as a user turn as required by Bedrock Converse API
        messages.append({"role": "user", "content": tool_results_content})

        return {
            "action": "INFERENCE",
            "messages": messages,
            "auth_context": verified_ctx.to_dict(),
            "iteration": iteration,
        }

    else:
        raise ValueError(f"Unsupported action: {action}")

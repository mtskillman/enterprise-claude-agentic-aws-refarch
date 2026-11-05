"""Step Functions Agentic Worker Lambda Handler.

Handles dual execution modes within the Step Functions state machine:
1. 'INFERENCE': Invocates Anthropic Claude on Amazon Bedrock with tools.
2. 'TOOL_EXECUTION': Dispatches tool calls requested by Claude and returns results.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

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


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    action = event.get("action", "INFERENCE")
    tenant_id = event.get("tenant_id", "default")
    messages = event.get("messages", [])
    iteration = event.get("iteration", 0)

    # Initialize tools
    rag_tool = OpenSearchRAGRetrieverTool()
    calc_tool = SafeCalculatorTool()
    tool_map = {
        rag_tool.name: rag_tool,
        calc_tool.name: calc_tool,
    }

    if action == "INFERENCE":
        client = ClaudeBedrockClient()
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
            "tenant_id": tenant_id,
            "iteration": iteration,
        }

    else:
        raise ValueError(f"Unsupported action: {action}")

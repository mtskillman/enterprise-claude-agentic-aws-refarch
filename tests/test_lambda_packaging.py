"""Smoke tests that load every Lambda handler the way the Lambda runtime does.

Terraform zips the *contents* of `src/` as the deployment package, so handlers resolve as
top-level packages (`auth.handler`, `orchestrator.handler`, `ingestion.handler`). These
tests put `src/` on sys.path and import them by those exact names.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

for mod_name in [
    "boto3",
    "botocore",
    "botocore.exceptions",
    "opensearchpy",
    "opensearchpy.exceptions",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# Lambda handler strings configured in terraform/main.tf
LAMBDA_HANDLERS = [
    "auth.handler.lambda_handler",
    "orchestrator.handler.lambda_handler",
    "ingestion.handler.lambda_handler",
]


class TestLambdaPackaging(unittest.TestCase):
    def test_handlers_import_from_package_root(self) -> None:
        for handler in LAMBDA_HANDLERS:
            module_name, func_name = handler.rsplit(".", 1)
            with self.subTest(handler=handler):
                module = importlib.import_module(module_name)
                self.assertTrue(callable(getattr(module, func_name)))

    def test_generate_turn_executes(self) -> None:
        from orchestrator.claude_client import ClaudeBedrockClient
        from shared.config import AppConfig

        client = ClaudeBedrockClient(config=AppConfig(primary_model_id="us.anthropic.claude-sonnet-5"))
        client.client = MagicMock()
        client.client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 2},
        }

        with patch("sys.stdout", io.StringIO()):
            result = client.generate_turn(
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                system_prompt="test",
                tenant_id="tenant-alpha",
            )

        self.assertEqual(result["stop_reason"], "end_turn")
        sent = client.client.converse.call_args.kwargs
        self.assertEqual(sent["modelId"], "us.anthropic.claude-sonnet-5")
        self.assertNotIn("temperature", sent["inferenceConfig"])

    def test_ingestion_lets_collection_assign_document_ids(self) -> None:
        ingestion = importlib.import_module("ingestion.handler")

        os_client = MagicMock()
        os_client.indices.exists.return_value = True
        os_client.search.return_value = {"hits": {"hits": [{"_id": "old-1"}]}}
        s3_client = MagicMock()
        s3_client.get_object.return_value = {
            "Metadata": {},
            "Body": io.BytesIO(b"failover policy text"),
        }
        bedrock_client = MagicMock()
        bedrock_client.invoke_model.return_value = {
            "body": io.BytesIO(json.dumps({"embedding": [0.0] * 1024}).encode())
        }

        def fake_client(service: str, **_: object) -> MagicMock:
            return s3_client if service == "s3" else bedrock_client

        event = {
            "Records": [
                {"s3": {"bucket": {"name": "docs"}, "object": {"key": "tenants/tenant-alpha/p.md"}}}
            ]
        }
        with patch.object(ingestion.boto3, "client", side_effect=fake_client), patch.object(
            ingestion, "OpenSearch", return_value=os_client
        ):
            result = ingestion.lambda_handler(event, None)

        self.assertEqual(result["indexed_chunks"], 1)
        os_client.delete.assert_called_once_with(index=ingestion.AppConfig().opensearch_index_name, id="old-1")
        index_kwargs = os_client.index.call_args.kwargs
        self.assertNotIn("id", index_kwargs)
        self.assertEqual(index_kwargs["body"]["tenant_id"], "tenant-alpha")


if __name__ == "__main__":
    unittest.main()

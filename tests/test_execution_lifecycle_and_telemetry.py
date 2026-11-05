"""Unit tests verifying execution polling, result delivery, IDOR isolation, and EMF/OTel telemetry."""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock AWS SDK and OpenSearch dependencies
for mod_name in [
    "boto3",
    "botocore",
    "botocore.exceptions",
    "opensearchpy",
    "opensearchpy.exceptions",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from src.auth.handler import _handle_get_execution, _handle_start_execution, lambda_handler
from src.shared.config import AppConfig
from src.shared.telemetry import GenAITelemetry
from src.shared.tenant_context import TenantIsolationError, VerifiedTenantContext


class TestExecutionLifecycleAndTelemetry(unittest.TestCase):
    def setUp(self) -> None:
        self.signing_secret = "b" * 64
        self.config = AppConfig(
            aws_region="us-east-1",
            state_machine_arn="arn:aws:states:us-east-1:123456789012:stateMachine:enterprise-claude-agent-state-machine",
            tenant_context_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:tenant-hmac",
        )

    @patch("src.auth.handler._get_signing_secret")
    def test_post_execution_returns_202_with_poll_url(self, mock_secret: MagicMock) -> None:
        mock_secret.return_value = self.signing_secret

        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:enterprise-claude-agent-state-machine:exec-12345"
        }

        event = {
            "body": json.dumps({"prompt": "How do I secure OpenSearch VPC endpoints?"})
        }

        resp = _handle_start_execution(
            event=event,
            principal_sub="user-999",
            verified_tenant_id="tenant-acme",
            config=self.config,
            sfn_client=mock_sfn,
        )

        self.assertEqual(resp["statusCode"], 202)
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "ACCEPTED")
        self.assertEqual(body["execution_id"], "exec-12345")
        self.assertEqual(body["tenant_id"], "tenant-acme")
        self.assertEqual(body["poll_url"], "/v1/agent/executions/exec-12345")

    def test_get_execution_running_status_authorized(self) -> None:
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {
            "status": "RUNNING",
            "startDate": "2026-11-05T08:00:00Z",
            "input": json.dumps({
                "auth_context": {"tenant_id": "tenant-acme", "principal_sub": "user-999"},
                "messages": [{"role": "user", "content": [{"text": "Query"}]}],
            }),
        }

        event = {
            "pathParameters": {"execution_id": "exec-12345"}
        }

        resp = _handle_get_execution(
            event=event,
            principal_sub="user-999",
            verified_tenant_id="tenant-acme",
            config=self.config,
            sfn_client=mock_sfn,
        )

        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "RUNNING")
        self.assertEqual(body["execution_id"], "exec-12345")
        self.assertEqual(body["tenant_id"], "tenant-acme")

    def test_get_execution_running_cross_tenant_blocked(self) -> None:
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {
            "status": "RUNNING",
            "startDate": "2026-11-05T08:00:00Z",
            "input": json.dumps({
                "auth_context": {"tenant_id": "tenant-victim", "principal_sub": "victim-user"},
            }),
        }

        event = {
            "pathParameters": {"execution_id": "exec-running-victim"}
        }

        with self.assertRaises(TenantIsolationError):
            _handle_get_execution(
                event=event,
                principal_sub="attacker-user",
                verified_tenant_id="tenant-attacker",
                config=self.config,
                sfn_client=mock_sfn,
            )

    def test_get_execution_succeeded_delivers_response(self) -> None:
        mock_sfn = MagicMock()
        sfn_output = {
            "status": "SUCCEEDED",
            "auth_context": {
                "tenant_id": "tenant-acme",
                "principal_sub": "user-999",
            },
            "messages": [
                {"role": "user", "content": [{"text": "Hello"}]},
                {"role": "assistant", "content": [{"text": "Here is the architectural answer."}]},
            ],
            "iteration": 2,
            "telemetry": {
                "gen_ai.usage.estimated_cost_usd": 0.0084,
                "gen_ai.usage.total_tokens": 1520,
            },
        }
        mock_sfn.describe_execution.return_value = {
            "status": "SUCCEEDED",
            "input": json.dumps({
                "auth_context": {"tenant_id": "tenant-acme", "principal_sub": "user-999"},
            }),
            "output": json.dumps(sfn_output),
        }

        event = {
            "pathParameters": {"execution_id": "exec-12345"}
        }

        resp = _handle_get_execution(
            event=event,
            principal_sub="user-999",
            verified_tenant_id="tenant-acme",
            config=self.config,
            sfn_client=mock_sfn,
        )

        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "SUCCEEDED")
        self.assertEqual(body["final_response"], "Here is the architectural answer.")
        self.assertEqual(body["iterations"], 2)
        self.assertEqual(body["telemetry"]["gen_ai.usage.estimated_cost_usd"], 0.0084)

    def test_get_execution_idor_cross_tenant_blocked(self) -> None:
        mock_sfn = MagicMock()
        sfn_output = {
            "status": "SUCCEEDED",
            "auth_context": {
                "tenant_id": "tenant-victim",
                "principal_sub": "victim-user",
            },
            "messages": [{"role": "assistant", "content": [{"text": "Sensitive victim data."}]}],
        }
        mock_sfn.describe_execution.return_value = {
            "status": "SUCCEEDED",
            "input": json.dumps({
                "auth_context": {"tenant_id": "tenant-victim", "principal_sub": "victim-user"},
            }),
            "output": json.dumps(sfn_output),
        }

        event = {
            "pathParameters": {"execution_id": "exec-victim-123"}
        }

        # Caller belongs to attacker tenant
        with self.assertRaises(TenantIsolationError):
            _handle_get_execution(
                event=event,
                principal_sub="attacker-user",
                verified_tenant_id="tenant-attacker",
                config=self.config,
                sfn_client=mock_sfn,
            )

    def test_get_execution_failed_cross_tenant_blocked(self) -> None:
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {
            "status": "FAILED",
            "error": "InternalEngineFailure",
            "cause": "Sensitive internal stack trace",
            "input": json.dumps({
                "auth_context": {"tenant_id": "tenant-victim", "principal_sub": "victim-user"},
            }),
        }

        event = {
            "pathParameters": {"execution_id": "exec-failed-victim"}
        }

        with self.assertRaises(TenantIsolationError):
            _handle_get_execution(
                event=event,
                principal_sub="attacker-user",
                verified_tenant_id="tenant-attacker",
                config=self.config,
                sfn_client=mock_sfn,
            )

    def test_get_execution_missing_tenant_blocked(self) -> None:
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {
            "status": "SUCCEEDED",
            "input": json.dumps({"messages": []}),  # Missing auth_context / tenant_id
            "output": json.dumps({"messages": []}),
        }

        event = {
            "pathParameters": {"execution_id": "exec-missing-tenant"}
        }

        with self.assertRaises(TenantIsolationError):
            _handle_get_execution(
                event=event,
                principal_sub="any-user",
                verified_tenant_id="tenant-acme",
                config=self.config,
                sfn_client=mock_sfn,
            )

    def test_cloudwatch_emf_telemetry_emission(self) -> None:
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            attrs = GenAITelemetry.emit_turn_telemetry(
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=1000,
                output_tokens=200,
                tenant_id="tenant-alpha",
                latency_ms=450.5,
            )

        output_str = captured_stdout.getvalue()
        self.assertTrue(len(output_str) > 0)
        emf_json = json.loads(output_str.strip())

        # Verify CloudWatch EMF structure
        self.assertIn("_aws", emf_json)
        metrics_meta = emf_json["_aws"]["CloudWatchMetrics"][0]
        self.assertEqual(metrics_meta["Namespace"], "EnterpriseClaude/AgenticWorkflows")
        self.assertEqual(emf_json["TenantId"], "tenant-alpha")
        self.assertEqual(emf_json["InputTokens"], 1000)
        self.assertEqual(emf_json["OutputTokens"], 200)
        self.assertEqual(emf_json["TotalTokens"], 1200)
        self.assertEqual(emf_json["TurnLatencyMs"], 450.5)

        # Verify OpenTelemetry GenAI Semantic Convention attributes
        self.assertEqual(attrs["gen_ai.system"], "aws.bedrock")
        self.assertEqual(attrs["gen_ai.request.model"], "anthropic.claude-3-5-sonnet-20241022-v2:0")
        self.assertEqual(attrs["tenant.id"], "tenant-alpha")
        self.assertEqual(attrs["gen_ai.usage.estimated_cost_usd"], 0.006)


if __name__ == "__main__":
    unittest.main()

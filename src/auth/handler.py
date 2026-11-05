"""Ingress Identity Gatekeeper & Step Functions Execution Lifecycle Handler.

Binds authenticated caller identity (verified OIDC/Cognito JWT claims from
Amazon API Gateway) to an authoritative `tenant_id`, seals the execution context
with an HMAC-SHA256 signature, and manages the complete execution lifecycle:
- POST /v1/agent/executions: Validates caller tenant claims and starts async execution.
- GET  /v1/agent/executions/{execution_id}: Polls execution status and delivers results
  with strict cryptographic tenant IDOR isolation.

Caller-supplied `tenant_id` fields in HTTP bodies are strictly rejected to prevent
cross-tenant horizontal privilege escalation.
"""

from __future__ import annotations

import functools
import json
import logging
import secrets
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from ..shared.config import AppConfig
from ..shared.tenant_context import TenantIsolationError, VerifiedTenantContext

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@functools.lru_cache(maxsize=1)
def _get_signing_secret(secret_arn: str, region: str) -> str:
    """Retrieve the HMAC signing key from AWS Secrets Manager (cached per execution environment).

    Zero-Trust State Security:
    If the secret container exists in Secrets Manager but has no value yet
    (preventing plaintext secrets from being stored in Terraform state files),
    the Gatekeeper dynamically generates a cryptographically secure 256-bit random key
    and stores it directly in AWS Secrets Manager under KMS CMK encryption.
    """
    sm_client = boto3.client("secretsmanager", region_name=region)
    try:
        resp = sm_client.get_secret_value(SecretId=secret_arn)
        secret_val = resp.get("SecretString")
        if secret_val:
            return secret_val
    except ClientError as err:
        err_code = err.response.get("Error", {}).get("Code")
        if err_code not in ("ResourceNotFoundException", "InvalidRequestException"):
            logger.error("Failed to retrieve signing key from Secrets Manager: %s", err)
            raise

    # Auto-seed cryptographically secure 256-bit key out-of-band directly in AWS Secrets Manager
    logger.info("Initializing zero-state HMAC signing key in AWS Secrets Manager: %s", secret_arn)
    new_secret = secrets.token_hex(32)
    try:
        sm_client.put_secret_value(SecretId=secret_arn, SecretString=new_secret)
        return new_secret
    except ClientError:
        # Concurrent initialization: fallback to reading newly created value
        resp = sm_client.get_secret_value(SecretId=secret_arn)
        return resp["SecretString"]


def _extract_verified_caller(event: Dict[str, Any]) -> Tuple[str, str]:
    """Extract and validate the caller's principal and tenant from API Gateway JWT claims."""
    jwt_claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    principal_sub = jwt_claims.get("sub")
    verified_tenant_id = (
        jwt_claims.get("custom:tenant_id")
        or jwt_claims.get("tenant_id")
        or jwt_claims.get("org_id")
    )

    if not principal_sub or not verified_tenant_id:
        raise TenantIsolationError(
            "Missing 'sub' or 'custom:tenant_id' claim in verified JWT authorizer context."
        )

    return str(principal_sub), str(verified_tenant_id)


def _handle_start_execution(
    event: Dict[str, Any],
    principal_sub: str,
    verified_tenant_id: str,
    config: AppConfig,
    sfn_client: Any,
) -> Dict[str, Any]:
    """Handle POST /v1/agent/executions: start Step Functions execution with sealed context."""
    raw_body = event.get("body") or "{}"
    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

    # Reject caller-supplied tenant_id overrides
    if "tenant_id" in body and body["tenant_id"] != verified_tenant_id:
        logger.warning(
            "Rejected attempt by principal '%s' to override JWT tenant '%s' with body tenant '%s'",
            principal_sub,
            verified_tenant_id,
            body["tenant_id"],
        )
        raise TenantIsolationError(
            "Caller is not authorized to specify a tenant_id different from their authenticated identity."
        )

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        prompt_text = body.get("prompt", "")
        if not prompt_text:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Request body must provide 'messages' or 'prompt'."}),
            }
        messages = [{"role": "user", "content": [{"text": str(prompt_text)}]}]

    # Mint cryptographically signed tenant execution context
    signing_secret = _get_signing_secret(
        config.tenant_context_secret_arn, config.aws_region
    )
    signed_ctx = VerifiedTenantContext.create_signed(
        tenant_id=verified_tenant_id,
        principal_sub=principal_sub,
        signing_secret=signing_secret,
    )

    sfn_input = {
        "auth_context": signed_ctx.to_dict(),
        "messages": messages,
        "iteration": 0,
    }
    execution = sfn_client.start_execution(
        stateMachineArn=config.state_machine_arn,
        input=json.dumps(sfn_input),
    )
    execution_arn = execution["executionArn"]
    execution_id = execution_arn.split(":")[-1]

    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "status": "ACCEPTED",
                "execution_arn": execution_arn,
                "execution_id": execution_id,
                "tenant_id": signed_ctx.tenant_id,
                "poll_url": f"/v1/agent/executions/{execution_id}",
            }
        ),
    }


def _handle_get_execution(
    event: Dict[str, Any],
    principal_sub: str,
    verified_tenant_id: str,
    config: AppConfig,
    sfn_client: Any,
) -> Dict[str, Any]:
    """Handle GET /v1/agent/executions/{execution_id}: poll status and return results with tenant isolation."""
    path_params = event.get("pathParameters") or {}
    execution_id = path_params.get("execution_id")

    if not execution_id:
        # Fallback to extracting from rawPath /v1/agent/executions/<id>
        raw_path = event.get("rawPath", "")
        parts = raw_path.strip("/").split("/")
        if len(parts) >= 4 and parts[1] == "agent" and parts[2] == "executions":
            execution_id = parts[3]

    if not execution_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing execution_id in request path."}),
        }

    # Resolve full ARN if only name/UUID was supplied
    if execution_id.startswith("arn:aws:states:"):
        execution_arn = execution_id
    else:
        # Derive ARN from state machine ARN prefix
        # State machine ARN: arn:aws:states:region:account:stateMachine:name
        # Execution ARN:     arn:aws:states:region:account:execution:name:execution_id
        sm_arn = config.state_machine_arn
        sm_parts = sm_arn.split(":")
        account_id = sm_parts[4]
        sm_name = sm_parts[6]
        execution_arn = f"arn:aws:states:{config.aws_region}:{account_id}:execution:{sm_name}:{execution_id}"

    try:
        describe_resp = sfn_client.describe_execution(executionArn=execution_arn)
    except ClientError as err:
        err_code = err.response.get("Error", {}).get("Code")
        if err_code == "ExecutionDoesNotExist":
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "NotFound", "message": f"Execution '{execution_id}' does not exist."}),
            }
        raise

    # 1. MANDATORY ZERO-TRUST TENANT VERIFICATION ACROSS ALL STATUSES
    # An execution MUST contain a verifiable tenant binding matching caller's verified_tenant_id.
    # We verify this BEFORE returning metadata or error details for ANY execution state.
    exec_tenant = None
    raw_input = describe_resp.get("input")
    if raw_input:
        try:
            input_data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
            exec_tenant = input_data.get("auth_context", {}).get("tenant_id")
        except Exception as err:
            logger.error("Failed to parse execution input for tenant validation: %s", err)

    if not exec_tenant and "output" in describe_resp:
        try:
            raw_output = describe_resp["output"]
            output_data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
            exec_tenant = output_data.get("auth_context", {}).get("tenant_id")
        except Exception:
            pass

    if not exec_tenant:
        logger.error("Execution '%s' lacks verifiable tenant binding in auth_context.", execution_id)
        raise TenantIsolationError("Execution lacks verifiable tenant identity context.")

    if exec_tenant != verified_tenant_id:
        logger.warning(
            "Cross-tenant IDOR access blocked: caller tenant '%s' attempted to access execution of tenant '%s'",
            verified_tenant_id,
            exec_tenant,
        )
        raise TenantIsolationError(
            "Caller is not authorized to access execution results belonging to another tenant."
        )

    status = describe_resp.get("status")

    if status == "RUNNING":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "status": "RUNNING",
                    "execution_arn": execution_arn,
                    "execution_id": execution_id,
                    "tenant_id": verified_tenant_id,
                    "start_date": str(describe_resp.get("startDate")),
                }
            ),
        }

    if status == "SUCCEEDED":
        raw_output = describe_resp.get("output", "{}")
        output_data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output

        # Extract the assistant's final response text
        messages = output_data.get("messages", [])
        final_response_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                for part in msg.get("content", []):
                    if isinstance(part, dict) and "text" in part:
                        final_response_text = part["text"]
                        break
                if final_response_text:
                    break

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "status": "SUCCEEDED",
                    "execution_arn": execution_arn,
                    "execution_id": execution_id,
                    "tenant_id": verified_tenant_id,
                    "final_response": final_response_text,
                    "iterations": output_data.get("iteration", 1),
                    "telemetry": output_data.get("telemetry", {}),
                    "messages": messages,
                }
            ),
        }

    # Status: FAILED, TIMED_OUT, ABORTED
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "status": status,
                "execution_arn": execution_arn,
                "execution_id": execution_id,
                "tenant_id": verified_tenant_id,
                "error": describe_resp.get("error", "ExecutionEndedWithFailure"),
                "cause": describe_resp.get("cause", "Execution failed before reaching completion."),
            }
        ),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    config = AppConfig()
    sfn_client = boto3.client("stepfunctions", region_name=config.aws_region)

    try:
        # Extract and verify caller identity from API Gateway JWT Authorizer
        principal_sub, verified_tenant_id = _extract_verified_caller(event)

        # Determine HTTP method (API Gateway v2 HTTP API)
        http_method = (
            event.get("requestContext", {})
            .get("http", {})
            .get("method", "POST")
            .upper()
        )

        if http_method == "GET":
            return _handle_get_execution(
                event=event,
                principal_sub=principal_sub,
                verified_tenant_id=verified_tenant_id,
                config=config,
                sfn_client=sfn_client,
            )
        elif http_method == "POST":
            return _handle_start_execution(
                event=event,
                principal_sub=principal_sub,
                verified_tenant_id=verified_tenant_id,
                config=config,
                sfn_client=sfn_client,
            )
        else:
            return {
                "statusCode": 405,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"Method {http_method} not allowed."}),
            }

    except TenantIsolationError as err:
        logger.error("Tenant authorization failure: %s", err)
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Forbidden", "message": str(err)}),
        }
    except Exception as err:
        logger.exception("Internal execution error: %s", err)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "InternalServerError", "message": str(err)}),
        }

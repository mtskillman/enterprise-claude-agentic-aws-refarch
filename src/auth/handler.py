"""Ingress Identity Gatekeeper & Step Functions Execution Starter.

Binds authenticated caller identity (verified OIDC/Cognito JWT claims from
Amazon API Gateway) to an authoritative `tenant_id`, seals the execution context
with an HMAC-SHA256 signature, and starts the Step Functions state machine.

Caller-supplied `tenant_id` fields in the HTTP body are ignored to prevent
cross-tenant horizontal privilege escalation.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Dict

import boto3

from ..shared.config import AppConfig
from ..shared.tenant_context import TenantIsolationError, VerifiedTenantContext

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@functools.lru_cache(maxsize=1)
def _get_signing_secret(secret_arn: str, region: str) -> str:
    """Retrieve the HMAC signing key from AWS Secrets Manager (cached per execution environment)."""
    sm_client = boto3.client("secretsmanager", region_name=region)
    resp = sm_client.get_secret_value(SecretId=secret_arn)
    return resp["SecretString"]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    config = AppConfig()
    sfn_client = boto3.client("stepfunctions", region_name=config.aws_region)

    try:
        # 1. Extract verified JWT claims injected by API Gateway JWT Authorizer
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

        # 2. Parse user prompt / messages from request body (ignoring any body tenant_id)
        raw_body = event.get("body") or "{}"
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
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
                    "body": json.dumps({"error": "Request body must provide 'messages' or 'prompt'."}),
                }
            messages = [{"role": "user", "content": [{"text": str(prompt_text)}]}]

        # 3. Mint cryptographically signed tenant execution context
        signing_secret = _get_signing_secret(
            config.tenant_context_secret_arn, config.aws_region
        )
        signed_ctx = VerifiedTenantContext.create_signed(
            tenant_id=str(verified_tenant_id),
            principal_sub=str(principal_sub),
            signing_secret=signing_secret,
        )

        # 4. Start Step Functions execution with sealed auth_context
        sfn_input = {
            "auth_context": signed_ctx.to_dict(),
            "messages": messages,
            "iteration": 0,
        }
        execution = sfn_client.start_execution(
            stateMachineArn=config.state_machine_arn,
            input=json.dumps(sfn_input),
        )

        return {
            "statusCode": 202,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "status": "ACCEPTED",
                    "execution_arn": execution["executionArn"],
                    "tenant_id": signed_ctx.tenant_id,
                }
            ),
        }

    except TenantIsolationError as err:
        logger.error("Tenant authorization failure: %s", err)
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Forbidden", "message": str(err)}),
        }

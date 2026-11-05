"""Cryptographic Tenant Identity Binding and Isolation Verification.

Ensures tenant_id is never trusted from unverified caller payloads or mutable
S3 object metadata.
- Query path: The API Gateway / Ingress Authorizer validates the caller's OIDC/JWT
  token, extracts the authoritative tenant claim, and seals it with an HMAC-SHA256
  signature before starting the Step Functions state machine.
- Ingestion path: Tenant ownership is deterministically bound to the IAM-enforced
  S3 prefix `tenants/<tenant_id>/<object_key>` and cross-checked against metadata.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from typing import Any, Dict

TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")
MAX_CONTEXT_AGE_SECONDS = 3600  # 1 hour max execution validity


class TenantIsolationError(PermissionError):
    """Raised when tenant identity binding is missing, invalid, or tampered with."""


@dataclass(frozen=True)
class VerifiedTenantContext:
    """Immutable, cryptographically verified tenant execution context."""

    tenant_id: str
    principal_sub: str
    issued_at: int
    signature: str

    @classmethod
    def create_signed(
        cls,
        tenant_id: str,
        principal_sub: str,
        signing_secret: str,
        issued_at: int | None = None,
    ) -> "VerifiedTenantContext":
        """Mint a cryptographically signed tenant context at the ingress boundary."""
        cls.validate_tenant_id_format(tenant_id)
        if not principal_sub:
            raise TenantIsolationError("Authenticated principal_sub is required.")
        if not signing_secret:
            raise TenantIsolationError("Signing secret is not configured.")

        ts = issued_at if issued_at is not None else int(time.time())
        sig = cls._compute_hmac(
            tenant_id=tenant_id,
            principal_sub=principal_sub,
            issued_at=ts,
            signing_secret=signing_secret,
        )
        return cls(
            tenant_id=tenant_id,
            principal_sub=principal_sub,
            issued_at=ts,
            signature=sig,
        )

    @classmethod
    def from_untrusted_dict(
        cls,
        auth_context: Dict[str, Any] | None,
        signing_secret: str,
        now_ts: int | None = None,
    ) -> "VerifiedTenantContext":
        """Verify HMAC signature and expiration on an incoming Step Functions auth_context."""
        if not isinstance(auth_context, dict):
            raise TenantIsolationError(
                "Missing or malformed auth_context; direct unauthenticated invocation is prohibited."
            )

        tenant_id = str(auth_context.get("tenant_id", ""))
        principal_sub = str(auth_context.get("principal_sub", ""))
        signature = str(auth_context.get("signature", ""))
        try:
            issued_at = int(auth_context.get("issued_at", 0))
        except (TypeError, ValueError) as exc:
            raise TenantIsolationError("Invalid issued_at timestamp in auth_context.") from exc

        cls.validate_tenant_id_format(tenant_id)
        if not principal_sub or not signature:
            raise TenantIsolationError("Incomplete auth_context fields.")
        if not signing_secret:
            raise TenantIsolationError("Signing secret is not configured.")

        current_time = now_ts if now_ts is not None else int(time.time())
        if current_time - issued_at > MAX_CONTEXT_AGE_SECONDS or issued_at > current_time + 60:
            raise TenantIsolationError("Tenant auth_context has expired or has an invalid clock skew.")

        expected_sig = cls._compute_hmac(
            tenant_id=tenant_id,
            principal_sub=principal_sub,
            issued_at=issued_at,
            signing_secret=signing_secret,
        )
        if not hmac.compare_digest(signature, expected_sig):
            raise TenantIsolationError(
                "Cryptographic signature mismatch on auth_context; possible tenant spoofing attempt."
            )

        return cls(
            tenant_id=tenant_id,
            principal_sub=principal_sub,
            issued_at=issued_at,
            signature=signature,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "principal_sub": self.principal_sub,
            "issued_at": self.issued_at,
            "signature": self.signature,
        }

    @staticmethod
    def validate_tenant_id_format(tenant_id: str) -> None:
        if not tenant_id or not TENANT_ID_PATTERN.match(tenant_id):
            raise TenantIsolationError(
                f"Invalid tenant_id '{tenant_id}'. Must match {TENANT_ID_PATTERN.pattern}."
            )

    @staticmethod
    def _compute_hmac(
        tenant_id: str,
        principal_sub: str,
        issued_at: int,
        signing_secret: str,
    ) -> str:
        canonical = f"v1:{tenant_id}:{principal_sub}:{issued_at}".encode("utf-8")
        return hmac.new(
            signing_secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()


def extract_verified_tenant_from_s3_key(
    s3_key: str, object_metadata: Dict[str, str] | None = None
) -> str:
    """Extract and validate tenant_id from an IAM-enforced S3 prefix `tenants/<tenant_id>/<doc>`.

    Rejects objects uploaded outside the `tenants/` hierarchy or where user-supplied
    object metadata attempts to override the prefix-bound tenant_id.
    """
    normalized_key = s3_key.lstrip("/")
    parts = normalized_key.split("/")
    if len(parts) < 3 or parts[0] != "tenants" or ".." in parts:
        raise TenantIsolationError(
            f"S3 key '{s3_key}' violates mandatory tenant prefix structure 'tenants/<tenant_id>/<document>'."
        )

    prefix_tenant_id = parts[1]
    VerifiedTenantContext.validate_tenant_id_format(prefix_tenant_id)

    if object_metadata:
        meta_tenant = object_metadata.get("tenant-id") or object_metadata.get("tenant_id")
        if meta_tenant and meta_tenant != prefix_tenant_id:
            raise TenantIsolationError(
                f"S3 object metadata tenant '{meta_tenant}' conflicts with IAM-enforced key prefix tenant '{prefix_tenant_id}'."
            )

    return prefix_tenant_id

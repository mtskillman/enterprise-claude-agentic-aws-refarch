"""Unit tests verifying cryptographic tenant isolation, S3 prefix binding, and vector index schema."""

from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import MagicMock

# Mock AWS SDK and OpenSearch client dependencies so unit tests run in standard environments
for mod_name in [
    "boto3",
    "botocore",
    "botocore.exceptions",
    "opensearchpy",
    "opensearchpy.exceptions",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Import modules exactly as the Lambda runtime does: `src/` is the deployment package root.
import os  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from orchestrator.tools.calculator import SafeCalculatorTool
from shared.opensearch_index import EMBEDDING_DIMENSIONS, KNOWLEDGE_BASE_INDEX_BODY
from shared.tenant_context import (
    TenantIsolationError,
    VerifiedTenantContext,
    extract_verified_tenant_from_s3_key,
)


class TestTenantIsolationAndSecurity(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "a" * 64

    def test_valid_signed_tenant_context_roundtrip(self) -> None:
        ctx = VerifiedTenantContext.create_signed(
            tenant_id="tenant-alpha",
            principal_sub="user-1234",
            signing_secret=self.secret,
        )
        verified = VerifiedTenantContext.from_untrusted_dict(
            ctx.to_dict(), signing_secret=self.secret
        )
        self.assertEqual(verified.tenant_id, "tenant-alpha")
        self.assertEqual(verified.principal_sub, "user-1234")

    def test_tampered_tenant_id_rejected(self) -> None:
        ctx = VerifiedTenantContext.create_signed(
            tenant_id="tenant-alpha",
            principal_sub="user-1234",
            signing_secret=self.secret,
        )
        payload = ctx.to_dict()
        payload["tenant_id"] = "tenant-beta"  # Attacker attempts horizontal escalation

        with self.assertRaises(TenantIsolationError):
            VerifiedTenantContext.from_untrusted_dict(payload, signing_secret=self.secret)

    def test_expired_context_rejected(self) -> None:
        now = int(time.time())
        ctx = VerifiedTenantContext.create_signed(
            tenant_id="tenant-alpha",
            principal_sub="user-1234",
            signing_secret=self.secret,
            issued_at=now - 7200,
        )
        with self.assertRaises(TenantIsolationError):
            VerifiedTenantContext.from_untrusted_dict(
                ctx.to_dict(), signing_secret=self.secret, now_ts=now
            )

    def test_s3_key_prefix_tenant_extraction(self) -> None:
        tenant = extract_verified_tenant_from_s3_key(
            "tenants/engineering-dept/architecture/policy.md",
            {"title": "Policy"},
        )
        self.assertEqual(tenant, "engineering-dept")

    def test_s3_key_outside_tenants_prefix_rejected(self) -> None:
        with self.assertRaises(TenantIsolationError):
            extract_verified_tenant_from_s3_key("public/policy.md")

    def test_s3_metadata_conflict_rejected(self) -> None:
        with self.assertRaises(TenantIsolationError):
            extract_verified_tenant_from_s3_key(
                "tenants/tenant-alpha/doc.md",
                {"tenant-id": "tenant-beta"},
            )

    def test_opensearch_vector_index_mapping_schema(self) -> None:
        self.assertEqual(EMBEDDING_DIMENSIONS, 1024)
        props = KNOWLEDGE_BASE_INDEX_BODY["mappings"]["properties"]
        self.assertEqual(props["embedding"]["type"], "knn_vector")
        self.assertEqual(props["embedding"]["dimension"], 1024)
        self.assertEqual(props["embedding"]["method"]["name"], "hnsw")
        self.assertEqual(props["tenant_id"]["type"], "keyword")

    def test_safe_calculator_ast(self) -> None:
        calc = SafeCalculatorTool()
        res = calc.execute({"expression": "14500 * 12"})
        self.assertEqual(res["result"], 174000)


if __name__ == "__main__":
    unittest.main()

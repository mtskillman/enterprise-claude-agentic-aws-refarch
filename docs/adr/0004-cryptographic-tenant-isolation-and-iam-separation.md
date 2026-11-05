# ADR 0004: Cryptographic Tenant Identity Binding & Least-Privilege Role Separation

## Status
Accepted

## Context
In a multi-tenant enterprise RAG and agentic platform, relying on caller-supplied `tenant_id` parameters in workflow inputs or user-mutable S3 object metadata creates a critical horizontal privilege escalation (IDOR) vulnerability. Furthermore, sharing a single AWS Lambda execution role across document ingestion and query orchestration violates the principle of least privilege.

## Decision
We enforce **Defense-in-Depth Multi-Tenant Isolation** and **Strict IAM/Data-Plane Separation** across three boundaries:

1. **Query Path — Authenticated JWT Ingress & Cryptographic Context Sealing**:
   - Callers authenticate via **Amazon API Gateway (HTTP API)** backed by an **Amazon Cognito / OIDC JWT Authorizer**.
   - The **Auth Gatekeeper Lambda** (`src/auth/handler.py`) extracts the immutable `custom:tenant_id` claim directly from the verified JWT token context and rejects any request body attempting to override `tenant_id`.
   - The Gatekeeper mints a `VerifiedTenantContext` (`src/shared/tenant_context.py`) signed with an **HMAC-SHA256** key stored in KMS-encrypted AWS Secrets Manager.
   - Every turn in the **AWS Step Functions** loop passes `auth_context`, and the **Orchestrator Lambda** (`src/orchestrator/handler.py`) verifies the HMAC signature and expiration timestamp before invoking Bedrock or executing k-NN retrieval.

2. **Ingestion Path — IAM-Governed S3 Prefix Binding**:
   - S3 bucket policies (`DenyUploadsOutsidePrincipalTenantPrefix`) restrict `s3:PutObject` to `s3://<bucket>/tenants/${aws:PrincipalTag/tenant_id}/*`.
   - The **Ingestion Lambda** (`src/ingestion/handler.py`) derives `tenant_id` deterministically from the top-level `tenants/<tenant_id>/...` S3 key path via `extract_verified_tenant_from_s3_key()` and aborts with `TenantIsolationError` if user-supplied S3 metadata conflicts with the prefix.

3. **Compute & Data-Plane Role Separation**:
   - **Orchestrator Role (`orchestrator_exec`)**: Has **zero S3 permissions**, invokes Claude Sonnet/Haiku and Titan Embeddings v2, and is restricted by the OpenSearch Serverless Data Access Policy to **read-only** (`aoss:ReadDocument`, `aoss:DescribeIndex`).
   - **Ingestion Role (`ingestion_exec`)**: Has **zero Claude generative model permissions** (scoped strictly to `amazon.titan-embed-text-v2:0`), read-only access to `s3://<bucket>/tenants/*`, and write access (`aoss:WriteDocument`, `aoss:CreateIndex`) in OpenSearch Serverless.

## Consequences

### Positive
- Eliminates cross-tenant horizontal privilege escalation even if an internal caller attempts to spoof payload fields.
- A compromise or prompt injection in the query orchestrator can never overwrite vector index records or access raw S3 documents.
- Ingestion workers cannot be abused to run expensive generative LLM completions.

### Trade-offs
- Adds a lightweight HMAC verification step and Secrets Manager cached lookup on orchestrator cold starts.

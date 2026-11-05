# ADR 0005: Lambda Dependency Layering, Execution Delivery Polling, and Zero-Trust State Hygiene

## Status
Accepted

## Context
Following the implementation of cryptographic tenant isolation (ADR 0004), three critical operational and architectural gaps were identified:
1. **Packaging & Dependency Omission**: The runtime package zipped only `src/`, omitting third-party dependencies (`opensearch-py`, `requests-aws4auth`). Because `terraform apply` executes `aws_lambda_invocation` to bootstrap the vector schema, the deployment failed on import.
2. **Incomplete Client Delivery Contract**: The API returned HTTP `202 ACCEPTED` with an execution ARN, but provided no API route to poll for execution status or retrieve the completed agent response. Clients could start reasoning tasks without receiving answers.
3. **Sensitive Data Persistence in Terraform State**: Generating the HMAC signing key in Terraform (`random_password`) stored the plaintext key in `terraform.tfstate`. In environments with shared or local state, this compromises the cryptographic isolation perimeter.
4. **Telemetry & FinOps Realism**: Telemetry calculations were purely computational without emitting real-time OpenTelemetry GenAI spans or CloudWatch metrics, and CloudWatch dashboards hardcoded `us-east-1`.

## Decision
We implement four architectural improvements across packaging, lifecycle delivery, state hygiene, and observability:

### 1. Deterministic Lambda Dependency Layering (`opensearch-py`)
- Standardized runtime requirements in `requirements.txt` (`opensearch-py==2.8.0`, `requests-aws4auth==1.3.1`, `requests>=2.31.0`).
- Automated layer build via `scripts/build_layer.sh` using cross-platform Linux x86_64 wheel compilation.
- Codified `aws_lambda_layer_version` (`opensearch_dependencies`) attached to both `orchestrator` and `ingestion` functions.
- Explicit Terraform dependency (`depends_on = [aws_lambda_layer_version.opensearch_dependencies]`) on the vector index bootstrapper invocation.

### 2. Full Async Lifecycle: Polling & Result Delivery with Tenant IDOR Isolation
- Codified API Gateway route `GET /v1/agent/executions/{execution_id}` with JWT Authorizer.
- Implemented `_handle_get_execution` in `src/auth/handler.py`:
  - When status is `RUNNING`: returns HTTP 200 with start timestamp and running status.
  - When status is `SUCCEEDED`: extracts output, **enforces that the execution's sealed `tenant_id` matches the caller's verified JWT `custom:tenant_id`**, and delivers the final assistant response text, iteration count, and telemetry.
  - When cross-tenant access is attempted (IDOR), the request is rejected with HTTP 403 Forbidden.
- Updated Step Functions state machine `FinalizeResponse` to explicitly format final output payloads.

### 3. Zero-Trust State Hygiene (Key Elimination from `.tfstate`)
- Removed `random_password` and `aws_secretsmanager_secret_version` with plaintext values from Terraform.
- Managed only the `aws_secretsmanager_secret` container with KMS CMK encryption and resource policies in Terraform.
- Implemented **dynamic zero-state runtime auto-seeding**: The Auth Gatekeeper dynamically generates a 256-bit cryptographically secure random key on first boot if unseeded, writing directly to Secrets Manager under KMS CMK encryption.
- Provided `scripts/seed_hmac_secret.sh` for out-of-band operator rotation via AWS CLI.
- Added `terraform/backend.tf.example` demonstrating production encrypted S3 remote state with DynamoDB locking.

### 4. True CloudWatch EMF & OpenTelemetry GenAI Emission
- Updated `src/shared/telemetry.py` to emit **CloudWatch Embedded Metric Format (EMF)** directly to stdout (`EnterpriseClaude/AgenticWorkflows` namespace with `TenantId` and `ModelId` dimensions).
- Emitted metrics: `EstimatedCostUSD`, `InputTokens`, `OutputTokens`, `TotalTokens`, and `TurnLatencyMs`.
- Updated CloudWatch dashboard to use dynamic `${var.aws_region}` and display real-time per-tenant FinOps costs, token consumption, and P95 latency.

## Consequences

### Positive
- Fully self-contained deployments: `terraform apply` succeeds deterministically with all Python dependencies staged.
- Complete API contract: callers can initiate queries and poll for validated, decrypted answers.
- State file compromises cannot leak HMAC signing keys, preserving horizontal tenant isolation.
- FinOps visibility: infrastructure operators and tenant administrators can monitor real-time dollar costs and token burn by tenant.

### Trade-offs
- First invocation of the Gatekeeper executes an initial KMS encryption call if the secret is unseeded.
- Callers must poll `GET /v1/agent/executions/{execution_id}` until execution finishes.

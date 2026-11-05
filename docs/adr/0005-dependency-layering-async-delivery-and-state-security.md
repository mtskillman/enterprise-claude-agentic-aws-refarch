# ADR 0005: Lambda Dependency Layering, Universal Tenant IDOR Isolation, and Execution Data Privacy

## Status
Accepted

## Context
Following the implementation of cryptographic tenant isolation (ADR 0004), deeper architectural analysis uncovered five operational and security vulnerabilities:
1. **Packaging & Build Fail-Safe**: The layer build script previously fell back to creating a dummy placeholder package if pip was missing. In automated pipelines, this would deploy an unusable layer and crash at runtime instead of failing fast during deployment.
2. **Incomplete Polling Tenant Verification**: Polling routes returned status early for `RUNNING` executions and error details for `FAILED` executions without first checking the execution's tenant binding. An attacker could probe execution IDs across tenants to discover running workflows or internal stack traces.
3. **Sensitive Prompt & Retrieval Data Leakage in CloudWatch**: Step Functions logged at `level = ALL` with `include_execution_data = true`, persisting full user prompts, retrieved confidential enterprise documents, and model completions in CloudWatch log streams for 30 days.
4. **IAM ARN Mismatch**: The Gatekeeper Lambda execution role allowed `DescribeExecution` under `${project_name}-orchestrator`, whereas the deployed state machine was named `${project_name}-agent-state-machine`.
5. **Observability Specificity**: The CloudWatch dashboard filtered tenant metrics to the literal string `"default"`, and Step Functions metric dimensions used an incorrect hardcoded state machine identifier.

## Decision
We enforce strict fail-fast packaging, comprehensive tenant authorization across all states, and zero-leakage workflow privacy:

### 1. Fail-Fast Lambda Dependency Packaging
- Standardized runtime requirements in `requirements.txt` (`opensearch-py==2.8.0`, `requests-aws4auth==1.3.1`, `requests>=2.31.0`, `opentelemetry-api`, `opentelemetry-sdk`).
- Updated `scripts/build_layer.sh` to immediately halt with `exit 1` if `pip3`/`pip` is unavailable or if `opensearchpy` fails to install, preventing phantom placeholder layers from deploying to AWS Lambda.
- Codified `aws_lambda_layer_version` (`opensearch_dependencies`) attached to both `orchestrator` and `ingestion` functions.

### 2. Universal Pre-Check Tenant IDOR Isolation Across All States
- In `src/auth/handler.py` (`_handle_get_execution`), tenant authorization executes **prior to inspecting any execution status**:
  - Extracts `tenant_id` from the sealed `auth_context` in execution `input` (and verifies `output` for completed executions).
  - Rejects missing tenant context with `TenantIsolationError` (HTTP 403).
  - Rejects mismatched caller tenant with `TenantIsolationError` (HTTP 403).
- Callers cannot discover running state, start timestamps, error causes, or output payloads belonging to other tenants.

### 3. Execution Data Privacy (Zero Log Leakage)
- Configured Step Functions logging in `terraform/modules/orchestrator_step_functions/main.tf` with `include_execution_data = false` and `level = "ERROR"`.
- Prevents raw prompts, retrieved knowledge passages, and assistant answers from being persisted into CloudWatch logs.

### 4. IAM ARN Scope Alignment
- In `terraform/main.tf`, bound the `states:DescribeExecution` resource dynamically to `${module.orchestrator_step_functions.state_machine_name}`:
  `arn:aws:states:${var.aws_region}:${account_id}:execution:${module.orchestrator_step_functions.state_machine_name}:*`
- Guarantees exact alignment between IAM policies and Step Functions execution ARNs.

### 5. Multi-Tenant CloudWatch Metric SEARCH & OpenTelemetry Spans
- Integrated OpenTelemetry distributed tracing in `src/shared/telemetry.py` emitting `gen_ai.client.turn` spans with standard GenAI semantic conventions.
- Updated `terraform/modules/observability_adot/main.tf` to use CloudWatch `SEARCH()` expressions (`SEARCH('{EnterpriseClaude/AgenticWorkflows,TenantId} MetricName="EstimatedCostUSD"', 'Sum', 300)`), dynamically plotting metrics across all real tenants.
- Bound Step Functions execution metrics directly to `var.state_machine_arn`.

## Consequences

### Positive
- Zero data leakage: Prompts and confidential documents never enter CloudWatch execution log streams.
- Complete IDOR protection: No execution status or error metadata is accessible across tenant boundaries.
- Build determinism: Missing build dependencies fail immediately in CI/CD rather than silently deploying broken layers.
- Real-time multi-tenant FinOps: CloudWatch dynamically visualizes actual tenant cost and token usage.

### Trade-offs
- Setting `include_execution_data = false` requires debugging specific state payloads via execution replay or authenticated API polling rather than CloudWatch logs.

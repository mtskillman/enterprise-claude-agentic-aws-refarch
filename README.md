# Enterprise Agentic GenAI Reference Architecture on AWS
### Powered by Anthropic Claude 3.5 Sonnet, Amazon Bedrock, OpenSearch Serverless & AWS Step Functions

[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock%20Converse%20API-FF9900?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Anthropic Claude](https://img.shields.io/badge/Model-Claude%203.5%20Sonnet-D97706?logo=anthropic&logoColor=white)](https://www.anthropic.com/claude)
[![OpenSearch Serverless](https://img.shields.io/badge/Vector%20Store-OpenSearch%20Serverless-005FD0?logo=opensearch&logoColor=white)](https://aws.amazon.com/opensearch-service/features/serverless/)
[![Step Functions](https://img.shields.io/badge/Orchestrator-AWS%20Step%20Functions-FF4F8B?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/step-functions/)
[![OpenTelemetry](https://img.shields.io/badge/Observability-OpenTelemetry%20%7C%20ADOT-4A154B?logo=opentelemetry&logoColor=white)](https://opentelemetry.io/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform%201.5%2B-7B42BC?logo=terraform&logoColor=white)](https://www.terraform.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Executive Summary

This repository presents an **enterprise-grade, production-hardened reference architecture** for deploying autonomous agentic workflows on AWS. Utilizing **Anthropic Claude 3.5 Sonnet** via the **Amazon Bedrock Converse API**, this architecture demonstrates how mission-critical enterprises can implement complex tool use, multi-step deterministic reasoning, cryptographically enforced multi-tenant hybrid retrieval-augmented generation (RAG), and zero-trust security without vendor lock-in or fragile in-memory agent loops.

Designed by an Anthropic Claude Certified Architect with over six years of leading AWS enterprise cloud migrations, this blueprint directly solves common enterprise GenAI failure modes:
1. **Unbounded Agent Loops & Timeouts**: Replacing brittle in-memory while-loops in containerized or Lambda runtimes with stateful, audit-ready **AWS Step Functions** orchestrators.
2. **Horizontal Privilege Escalation (IDOR) & Tenant Spoofing**: Replacing untrusted caller-supplied tenant arguments with **JWT-verified identity claims sealed via HMAC-SHA256** and storage-layer S3 tenant prefix boundaries.
3. **Network Perimeter Exposure**: Enforcing **strictly private network isolation** (`AllowFromPublic = false`) using dedicated **OpenSearch Serverless Interface VPC Endpoints** and private Lambda VPC subnets.
4. **Vector Mapping Drift**: Declaratively establishing explicit 1,024-dimensional HNSW k-NN vector schema definitions with automated index bootstrapping.
5. **Broad IAM Blast Radii**: Splitting permissions into **three dedicated least-privilege IAM roles** with zero cross-plane leakage between ingestion, query orchestration, and authentication.
6. **Data Leakage & Runaway Token Costs**: Enforcing dual-layer perimeter defense via **Amazon Bedrock Guardrails v1** and real-time **OpenTelemetry GenAI Semantic Convention** FinOps cost attribution.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph ClientAndIngress["1. Authenticated Ingress & Storage Layer"]
        User["User / Enterprise Client Application"]
        Cognito["Amazon Cognito / OIDC IdP<br/>(Issues JWT with custom:tenant_id)"]
        APIGW["Amazon API Gateway (HTTP API)<br/>• JWT Authorizer Enforces Token Validation<br/>• Scopes Access by Subject & Tenant"]
        GatekeeperLambda["Auth Gatekeeper Lambda<br/>• Extracts Verified JWT Tenant Claim<br/>• Rejects Body Tenant Overrides<br/>• Seals auth_context via HMAC-SHA256"]
        SecretsManager["AWS Secrets Manager<br/>(KMS CMK Encrypted Signing Key)"]
        S3Bucket["S3 Knowledge Documents Bucket<br/>(KMS CMK Encrypted)<br/>Prefix Enforced: tenants/{tenant_id}/*"]

        User -->|1. Authenticate| Cognito
        User -->|2. POST /v1/agent/executions (Bearer JWT)| APIGW
        APIGW --> GatekeeperLambda
        GatekeeperLambda <--> SecretsManager
    end

    subgraph SecurityPerimeter["2. Zero-Trust Security Perimeter"]
        Guardrails["Amazon Bedrock Guardrails v1<br/>• Automated PII Redaction (SSN, Email, CC)<br/>• Prompt Injection & Jailbreak Defense<br/>• Denied Topics & Boundary Checks"]
        KMS["AWS KMS Customer Managed Key (CMK)<br/>(Annual Auto-Rotation Enabled)"]
    end

    subgraph Orchestration["3. Agentic Orchestration Engine (AWS Step Functions)"]
        Init["Init Execution Context & Sealed auth_context"]
        InvokeClaude["Orchestrator Lambda: Invoke Claude 3.5 Sonnet<br/>• Validates HMAC Signature & Expiration<br/>• Scoped IAM Role (Zero S3 Access)"]
        InspectAction{"Tool Call<br/>Requested?"}
        ExecTools["Orchestrator Lambda: Execute Registered Tools<br/>• Hybrid BM25 + k-NN Search<br/>• Safe AST Arithmetic Calculator"]
        EvalLimit{"Iteration Count<br/>>= Max Steps?"}
        FormatResponse["Format & Return Final Answer"]
        AbortExecution["Halt with Timeout Safeguard"]

        GatekeeperLambda -->|3. start_execution(signed_context)| Init
        Init --> InvokeClaude
        InvokeClaude --> InspectAction
        InspectAction -- "Yes (tool_use)" --> ExecTools
        ExecTools --> EvalLimit
        EvalLimit -- "No" --> InvokeClaude
        EvalLimit -- "Yes" --> AbortExecution
        InspectAction -- "No (end_turn)" --> FormatResponse
    end

    subgraph PrivateVPC["4. Zero-Trust Private VPC (No Public Ingress)"]
        AOSS_VPCE["OpenSearch Serverless Interface VPC Endpoint<br/>• PrivateLink (AllowFromPublic = false)<br/>• Scoped Security Group"]
        Bedrock_VPCE["Bedrock Runtime VPC Endpoint"]
        S3_Gateway["S3 Gateway VPC Endpoint"]

        ExecTools --> AOSS_VPCE
        InvokeClaude --> Bedrock_VPCE
    end

    subgraph RAGStorage["5. Multi-Tenant Vector & Hybrid Store"]
        IngestionLambda["Ingestion Worker Lambda<br/>• Scoped IAM Role (No Claude LLM Access)<br/>• Enforces S3 key prefix: tenants/{tenant_id}/<br/>• Titan Embeddings v2 (1,024-dim)"]
        OpenSearch[("OpenSearch Serverless Collection<br/>• KMS CMK Encrypted (AWSOwnedKey = false)<br/>• Explicit 1,024-dim HNSW knn_vector Index<br/>• Mandatory Filter: tenant_id")]

        S3Bucket -- "s3:ObjectCreated (filter_prefix: tenants/)" --> IngestionLambda
        IngestionLambda --> S3_Gateway
        IngestionLambda --> AOSS_VPCE
        AOSS_VPCE --> OpenSearch
    end

    subgraph Observability["6. GenAI Observability & FinOps"]
        CW["Amazon CloudWatch Dashboards"]
        OTel["OpenTelemetry GenAI Traces & Spans"]
        CostTracker["Per-Invocation Cost Attribution"]
        
        InvokeClaude -.-> OTel
        OTel -.-> CW
        OTel -.-> CostTracker
    end

    InvokeClaude <--> Guardrails
    FormatResponse --> User
```

---

## Key Architectural Tenets

### 1. Cryptographic Tenant Identity Binding (Zero Trust)
In enterprise multi-tenant architectures, trusting a `tenant_id` supplied in request JSON or mutable S3 object metadata introduces an immediate horizontal privilege escalation (IDOR) vector. This blueprint enforces tenant identity at the cryptographic perimeter:
- **Query Path**: The caller authenticates via Cognito or an enterprise OIDC provider. Amazon API Gateway validates the JWT signature and audience. The **Auth Gatekeeper Lambda** extracts the verified `custom:tenant_id` claim from the token context and seals it into a `VerifiedTenantContext` using an **HMAC-SHA256 signature** backed by AWS Secrets Manager. Any attempt by a caller to supply a conflicting `tenant_id` in the request body is rejected with HTTP 403.
- **Workflow Verification**: Every step in the AWS Step Functions loop passes this sealed context. The orchestrator verifies the HMAC signature and timestamp before dispatching vector queries.
- **Ingestion Path**: The S3 bucket policy denies object uploads outside `s3://<bucket>/tenants/${aws:PrincipalTag/tenant_id}/*`. The ingestion worker deterministically extracts tenant ownership from the S3 key hierarchy (`tenants/<tenant_id>/<doc>`) and rejects mismatched user metadata.

### 2. Private Network Isolation (`AllowFromPublic = false`)
OpenSearch Serverless collections are frequently misconfigured with `AllowFromPublic = true`, relying solely on IAM data policies. This architecture enforces network-layer defense-in-depth:
- The OpenSearch network security policy sets `AllowFromPublic = false`.
- Ingress is restricted strictly to an **Interface VPC Endpoint** (`aws_opensearchserverless_vpc_endpoint`) hosted across private subnets.
- Orchestrator and Ingestion Lambdas are deployed in the private VPC with egress security groups scoped to private endpoints for Bedrock, Secrets Manager, and the S3 Gateway Endpoint.

### 3. Explicit 1,024-Dimensional HNSW Vector Indexing
Amazon Titan Text Embeddings v2 supports multiple dimensionalities (256, 512, 1024). This architecture standardizes on **1,024 dimensions with L2 normalization** for maximum retrieval accuracy.
- A declarative index mapping (`terraform/modules/opensearch_serverless/index_mapping.json`) defines the collection schema with `dynamic: strict`, `embedding` typed as `knn_vector` using `faiss/hnsw` with cosine similarity, and `tenant_id` typed as `keyword`.
- Terraform automatically executes an index bootstrapping invocation upon collection creation, guaranteeing that vector fields and analyzers are properly provisioned before ingestion or query traffic arrives.

### 4. Dedicated Customer Managed Key (KMS CMK) Encryption
To satisfy enterprise SOC2, HIPAA, and ISO 27001 requirements, 100% of persisted data is encrypted using a dedicated **Customer Managed Key (KMS CMK)** with annual rotation enabled:
- **OpenSearch Serverless**: Configured with `AWSOwnedKey = false` and bound directly to the KMS CMK ARN.
- **S3 Knowledge Bucket**: Enforces KMS server-side encryption with S3 Bucket Keys enabled.
- **AWS Secrets Manager**: Encrypts the HMAC tenant context signing secret with the KMS CMK.

### 5. Decomposed Least-Privilege IAM Roles
Rather than sharing a single broad execution role across services, the architecture enforces strict boundary separation across three specialized roles:
1. **Orchestrator Role (`orchestrator_exec`)**: Scoped to Bedrock Claude (Sonnet/Haiku) and Titan embeddings invoke, read-only search on OpenSearch Serverless (`aoss:ReadDocument`, `aoss:DescribeIndex`), and Secrets Manager HMAC secret read. **Has zero S3 bucket access.**
2. **Ingestion Role (`ingestion_exec`)**: Scoped to Titan embeddings invocation only (**cannot invoke Claude generative LLMs**), read-only access to `s3://<bucket>/tenants/*`, and write/index permissions on OpenSearch Serverless (`aoss:WriteDocument`, `aoss:CreateIndex`).
3. **Auth Gatekeeper Role (`auth_gatekeeper_exec`)**: Scoped strictly to starting Step Functions executions and reading the HMAC signing secret.

---

## Repository Structure

```text
.
├── LICENSE
├── README.md
├── docs/
│   └── adr/
│       ├── 0001-bedrock-claude-vs-direct-api.md
│       ├── 0002-opensearch-serverless-vs-pgvector.md
│       ├── 0003-step-functions-vs-in-memory-loops.md
│       └── 0004-cryptographic-tenant-isolation-and-iam-separation.md
├── src/
│   ├── auth/
│   │   ├── __init__.py
│   │   └── handler.py            # API Gateway JWT gatekeeper; mints signed tenant context
│   ├── shared/
│   │   ├── config.py             # Strongly typed pydantic environment settings
│   │   ├── opensearch_index.py   # Explicit 1,024-dim HNSW k-NN index schema & bootstrapper
│   │   ├── telemetry.py          # OpenTelemetry GenAI spans & FinOps cost calculation
│   │   └── tenant_context.py     # HMAC-SHA256 cryptographic tenant sealing & verification
│   ├── orchestrator/
│   │   ├── claude_client.py      # Bedrock Converse API client with Sonnet -> Haiku fallback
│   │   ├── handler.py            # Dual-mode Lambda worker (INFERENCE / TOOL_EXECUTION)
│   │   └── tools/
│   │       ├── base.py           # Abstract BaseTool with JSON schema generation
│   │       ├── rag_retriever.py  # OpenSearch Serverless hybrid BM25 + kNN retrieval
│   │       └── calculator.py     # Deterministic Python AST safe arithmetic evaluator
│   └── ingestion/
│       ├── chunker.py            # Sliding-window document chunking with overlap
│       └── handler.py            # S3 upload event worker & vector index bootstrapper
├── tests/
│   └── test_security_and_isolation.py # Unit tests for HMAC tenant isolation & schema validation
└── terraform/
    ├── main.tf                   # Root deployment module wiring all subsystems & VPC endpoints
    ├── variables.tf              # Configurable project variables & model IDs
    ├── outputs.tf                # Exported ARNs, API Gateway endpoints, and dashboard identifiers
    ├── versions.tf               # Terraform core and AWS provider version constraints
    ├── terraform.tfvars.example  # Production-ready configuration baseline
    └── modules/
        ├── security_kms_iam/     # Customer Managed Key (CMK) and key policies
        ├── opensearch_serverless/# Serverless collection, private VPCE, CMK encryption & data policies
        ├── bedrock_agent/        # Bedrock Guardrail definitions (PII & prompt safety)
        ├── orchestrator_step_functions/ # ASL agent state machine & execution roles
        └── observability_adot/   # CloudWatch telemetry & FinOps dashboards
```

---

## Architecture Decision Records (ADRs)

| ADR | Title | Decision Summary |
| :--- | :--- | :--- |
| [ADR-0001](docs/adr/0001-bedrock-claude-vs-direct-api.md) | Bedrock Claude vs. Direct Anthropic API | Leverage Amazon Bedrock for native IAM authentication, VPC endpoints, FedRAMP/HIPAA compliance, and Guardrails integration. |
| [ADR-0002](docs/adr/0002-opensearch-serverless-vs-pgvector.md) | OpenSearch Serverless vs. Amazon Aurora pgvector | Selected OpenSearch Serverless for combined BM25 keyword matching and dense vector search without database maintenance overhead. |
| [ADR-0003](docs/adr/0003-step-functions-vs-in-memory-loops.md) | Step Functions vs. In-Memory Agent Loops | Externalize agent control flow to Step Functions to bypass Lambda 15-minute limits, avoid runaway token burn, and capture auditable state. |
| [ADR-0004](docs/adr/0004-cryptographic-tenant-isolation-and-iam-separation.md) | Cryptographic Tenant Isolation & IAM Separation | Bind tenant identity via JWT authorizers and HMAC-SHA256 signatures; enforce S3 key prefixes and decompose Lambda execution roles. |

---

## Deployment & Getting Started

### Prerequisites
- [Terraform >= 1.5.0](https://www.terraform.io/downloads.html)
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured with Administrator permissions
- **Amazon Bedrock Model Access**: Ensure `anthropic.claude-3-5-sonnet-20241022-v2:0`, `anthropic.claude-3-5-haiku-20241022-v1:0`, and `amazon.titan-embed-text-v2:0` are enabled in your target AWS region (`us-east-1` or `us-west-2`).

### 1. Clone & Configure
```bash
git clone git@github.com:mtskillman/enterprise-claude-agentic-aws-refarch.git
cd enterprise-claude-agentic-aws-refarch/terraform

cp terraform.tfvars.example terraform.tfvars
```

### 2. Plan and Deploy
```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```
*Terraform deploys the VPC, OpenSearch Serverless collection, KMS CMK, Bedrock Guardrails, Step Functions state machine, and automatically triggers the index bootstrapper to initialize the 1,024-dim vector mapping.*

### 3. Ingest Enterprise Documents Under Tenant Prefix
Upload documents into the tenant-specific S3 key prefix:
```bash
DOCS_BUCKET=$(terraform output -raw knowledge_bucket_name)

# Ingest an engineering policy under tenant 'engineering-dept'
aws s3 cp sample-failover-policy.md s3://${DOCS_BUCKET}/tenants/engineering-dept/policies/failover.md
```
The Ingestion Lambda validates the `tenants/engineering-dept/` prefix, extracts passages, generates 1,024-dim Titan v2 embeddings, and indexes chunks tagged with `tenant_id: "engineering-dept"`.

### 4. Execute an Authenticated Agentic Query
Call the authenticated HTTP API with a valid Cognito/OIDC JWT Bearer token:
```bash
API_ENDPOINT=$(terraform output -raw api_gateway_endpoint)
BEARER_TOKEN="<VALID_COGNITO_JWT_TOKEN>"

curl -X POST "${API_ENDPOINT}" \
  -H "Authorization: Bearer ${BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is our company policy on multi-region failover, and what would be the total annual cost if our monthly bill is $14,500?"
  }'
```
The API Gateway authorizer verifies the JWT, the Gatekeeper seals the `custom:tenant_id` claim, and the Step Functions state machine executes the autonomous reasoning loop with strictly isolated hybrid RAG retrieval.

---

## Running Unit Tests

Run the security and schema validation suite locally:
```bash
python3 -m unittest discover tests
```

---

## Author & Attribution

**Matthew Skillman**  
*Anthropic Claude Certified Architect Professional | AWS Enterprise Solutions Architect*  
- **GitHub**: [@mtskillman](https://github.com/mtskillman)  
- **LinkedIn**: [linkedin.com/in/matthew-skillman](https://linkedin.com/in/matthew-skillman)  
- **Articles & Insights**: [caylent.com/insights](https://caylent.com/insights?author=57d88ca842a84e63b0ee95e1d9156d5a)

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

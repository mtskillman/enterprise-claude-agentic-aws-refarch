# ADR 0001: Anthropic Claude via Amazon Bedrock vs. Direct API

## Status
Accepted

## Context
Enterprise applications adopting Large Language Models (LLMs) must balance model capabilities (reasoning, tool-calling, speed) with strict enterprise compliance boundaries, data perimeter residency, private networking, and unified identity governance (IAM). We evaluated deploying **Anthropic Claude 3.5 Sonnet / Haiku** via **Amazon Bedrock** versus routing API traffic directly to Anthropic's public endpoints (`api.anthropic.com`).

## Decision
We deploy Anthropic Claude models strictly via **Amazon Bedrock** using AWS VPC Endpoints (AWS PrivateLink) and IAM role-based authorization.

## Consequences

### Positive
- **Data Perimeter & Compliance:** Prompt payloads and model completions never traverse the public internet. Bedrock guarantees customer data is encrypted in transit and at rest using Customer Managed Keys (AWS KMS) and is never used to train base models.
- **Unified Identity & Authorization:** Model invocations use standard AWS SigV4 signed requests and IAM policies, eliminating API token sprawling and third-party secret storage in AWS Secrets Manager.
- **Enterprise Guardrails:** Native integration with **Amazon Bedrock Guardrails** provides real-time PII redaction, toxic content filtering, and prompt injection defense at the infrastructure tier before reaching model context.
- **Cross-Region Resilience:** Bedrock Cross-Region Inference automatically shifts traffic to adjacent AWS regions during peak regional demand with zero code changes.

### Trade-offs
- Model feature parity on Bedrock follows Anthropic direct API releases by days or weeks.
- Requires AWS Bedrock model entitlement activation per account.

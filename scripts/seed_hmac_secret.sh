#!/usr/bin/env bash
# ==============================================================================
# Script: seed_hmac_secret.sh
# Purpose: Seed or rotate the HMAC-SHA256 signing secret in AWS Secrets Manager
# Security: Generates a 256-bit cryptographic random key and writes directly to
#           AWS Secrets Manager with KMS CMK encryption. Plaintext never touches
#           Terraform state or local disk.
# ==============================================================================

set -euo pipefail

SECRET_NAME="${1:-enterprise-claude-refarch-prod-tenant-hmac-secret}"
REGION="${AWS_REGION:-${2:-us-east-1}}"

echo "==> Generating 256-bit cryptographically secure HMAC secret..."
NEW_KEY=$(openssl rand -hex 32)

echo "==> Storing key in AWS Secrets Manager: ${SECRET_NAME} (Region: ${REGION})"
aws secretsmanager put-secret-value \
    --secret-id "${SECRET_NAME}" \
    --secret-string "${NEW_KEY}" \
    --region "${REGION}"

echo "==> Successfully updated HMAC signing key in Secrets Manager (zero Terraform state persistence)."

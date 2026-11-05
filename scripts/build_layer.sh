#!/usr/bin/env bash
# ==============================================================================
# Script: build_layer.sh
# Purpose: Build AWS Lambda Dependency Layer containing opensearch-py and requests
# Runtime Target: Python 3.11 (Linux x86_64 / arm64)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAYER_BUILD_DIR="${REPO_ROOT}/terraform/build/layer/python"

echo "==> Preparing Lambda Layer build directory at: ${LAYER_BUILD_DIR}"
rm -rf "${REPO_ROOT}/terraform/build/layer"
mkdir -p "${LAYER_BUILD_DIR}"

REQUIREMENTS_FILE="${REPO_ROOT}/requirements.txt"

if [ ! -f "${REQUIREMENTS_FILE}" ]; then
    echo "ERROR: requirements.txt not found at ${REQUIREMENTS_FILE}"
    exit 1
fi

echo "==> Locating Python package installer..."
if command -v pip3 &> /dev/null; then
    PIP_CMD="pip3"
elif command -v pip &> /dev/null; then
    PIP_CMD="pip"
else
    echo "ERROR: Neither pip3 nor pip found in PATH. Cannot build Lambda dependency layer." >&2
    exit 1
fi

# Attempt binary wheels for Linux Python 3.11; fallback to standard target install
if ${PIP_CMD} install \
    --target "${LAYER_BUILD_DIR}" \
    --requirement "${REQUIREMENTS_FILE}" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.11 \
    --only-binary=:all: 2>/dev/null; then
    echo "==> Successfully installed Linux x86_64 binary wheels for Python 3.11."
else
    echo "==> Cross-platform flags not supported by local pip; installing standard wheels..."
    ${PIP_CMD} install \
        --target "${LAYER_BUILD_DIR}" \
        --requirement "${REQUIREMENTS_FILE}" \
        --no-user
fi

# Verify required production modules were actually installed
if [ ! -d "${LAYER_BUILD_DIR}/opensearchpy" ]; then
    echo "ERROR: Required package 'opensearchpy' was not found in ${LAYER_BUILD_DIR}." >&2
    exit 1
fi

# Clean up unwanted artifacts
find "${LAYER_BUILD_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${LAYER_BUILD_DIR}" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

echo "==> Lambda Layer build completed successfully."

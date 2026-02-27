#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

ENV_NAME="${ENV_NAME:-xagent}"
MODEL_NAME="${MODEL_NAME:-qwen2-0.5b-ov}"
LOG_FILE="${LOG_FILE:-/tmp/step9_twowait_debug_v5.log}"
STRICT_GATEWAY_WAIT="${STRICT_GATEWAY_WAIT:-0}"

echo "[e2e] ENV_NAME=$ENV_NAME"
echo "[e2e] MODEL_NAME=$MODEL_NAME"
echo "[e2e] LOG_FILE=$LOG_FILE"
echo "[e2e] STRICT_GATEWAY_WAIT=$STRICT_GATEWAY_WAIT"

MANUAL_PROVIDER=1 \
ENV_NAME="$ENV_NAME" \
MODEL_NAME="$MODEL_NAME" \
STRICT_GATEWAY_WAIT="$STRICT_GATEWAY_WAIT" \
bash scripts/test_openclaw_gateway_e2e.sh | tee "$LOG_FILE"

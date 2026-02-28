#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-xagent}"
STRICT="${STRICT:-1}"
AGENT_WAIT_TIMEOUT_MS="${AGENT_WAIT_TIMEOUT_MS:-300000}"
MAU_LOG_FILE="${MAU_LOG_FILE:-/tmp/mau_e2e_test.log}"

echo "[mau-e2e] ENV_NAME=$ENV_NAME"
echo "[mau-e2e] STRICT=$STRICT"
echo "[mau-e2e] AGENT_WAIT_TIMEOUT_MS=$AGENT_WAIT_TIMEOUT_MS"
echo "[mau-e2e] MAU_LOG_FILE=$MAU_LOG_FILE"

echo "[mau-e2e] checking manual provider health at http://127.0.0.1:18080/health ..."
if ! curl -sS --max-time 2 http://127.0.0.1:18080/health >/dev/null 2>&1; then
	echo "[mau-e2e][ERROR] provider is not running on 127.0.0.1:18080"
	echo "[mau-e2e][HINT] start it first in another terminal: ./run_manual_provider.sh"
	exit 1
fi

MANUAL_PROVIDER=1 \
ENV_NAME="$ENV_NAME" \
STRICT_GATEWAY_WAIT="$STRICT" \
AGENT_WAIT_TIMEOUT_MS="$AGENT_WAIT_TIMEOUT_MS" \
bash scripts/test_openclaw_gateway_e2e.sh 2>&1 | tee "$MAU_LOG_FILE"

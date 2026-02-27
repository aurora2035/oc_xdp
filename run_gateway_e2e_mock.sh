#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=========================================="
echo "OpenClaw Gateway E2E Test (Mock Mode)"
echo "=========================================="
echo ""
echo "This script runs E2E test using MOCK SERVER"
echo "Expected time: 30-60 seconds (vs 5+ minutes with real model)"
echo ""

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

ENV_NAME="${ENV_NAME:-xagent}"
MODEL_NAME="${MODEL_NAME:-mock-model}"
LOG_FILE="${LOG_FILE:-/tmp/step9_mock_test.log}"
STRICT_GATEWAY_WAIT="${STRICT_GATEWAY_WAIT:-0}"

echo "[e2e-mock] ENV_NAME=$ENV_NAME"
echo "[e2e-mock] MODEL_NAME=$MODEL_NAME"
echo "[e2e-mock] LOG_FILE=$LOG_FILE"
echo "[e2e-mock] STRICT_GATEWAY_WAIT=$STRICT_GATEWAY_WAIT"
echo ""

# 使用 mock server 启动 provider
# MOCK_MODE=1 使用 mock server
# MOCK_MODE=0 使用真实模型
echo "[e2e-mock] Starting mock server in background..."

# 清理旧进程
pkill -f "openai_mock_server.py" 2>/dev/null || true
pkill -f "openvino_openai_provider" 2>/dev/null || true
sleep 2
lsof -ti:18080 | xargs -r kill -9 2>/dev/null || true
sleep 1

# 启动 mock server
/root/miniconda3/envs/xagent/bin/python openai_mock_server.py \
  --host 127.0.0.1 \
  --port 18080 \
  > /tmp/mock_server_e2e.log 2>&1 &

MOCK_PID=$!
echo "[e2e-mock] Mock server PID: $MOCK_PID"

# 等待 mock server 启动
echo "[e2e-mock] Waiting for mock server..."
for i in {1..30}; do
  if curl -s http://127.0.0.1:18080/health >/dev/null 2>&1; then
    echo "[e2e-mock] Mock server is ready!"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "[e2e-mock] ERROR: Mock server failed to start"
    tail -20 /tmp/mock_server_e2e.log
    exit 1
  fi
  sleep 1
done

# 设置清理函数
cleanup() {
  echo ""
  echo "[cleanup] Stopping mock server..."
  kill $MOCK_PID 2>/dev/null || true
  wait $MOCK_PID 2>/dev/null || true
  exit ${1:-0}
}
trap cleanup EXIT INT TERM

echo ""
echo "=========================================="
echo "Running E2E test with mock server..."
echo "=========================================="
echo ""

# 运行 E2E 测试
# 使用 mock server 时，超时可以设置短一些
MANUAL_PROVIDER=1 \
ENV_NAME="$ENV_NAME" \
MODEL_NAME="$MODEL_NAME" \
STRICT_GATEWAY_WAIT="$STRICT_GATEWAY_WAIT" \
AGENT_WAIT_TIMEOUT_MS="${AGENT_WAIT_TIMEOUT_MS:-60000}" \
bash scripts/test_openclaw_gateway_e2e.sh 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "=========================================="
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "✅ E2E Test PASSED!"
else
  echo "❌ E2E Test FAILED (exit code: $EXIT_CODE)"
fi
echo "=========================================="
echo "Log file: $LOG_FILE"
echo "Mock server log: /tmp/mock_server_e2e.log"

exit $EXIT_CODE

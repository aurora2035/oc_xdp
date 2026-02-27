#!/usr/bin/env bash
set -euo pipefail

export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT_DIR/../openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$ROOT_DIR/.openclaw}"
ENABLE_MOCK_MODEL="${ENABLE_MOCK_MODEL:-1}"
USE_LOCAL_PROVIDER="${USE_LOCAL_PROVIDER:-0}"
LOCAL_PROVIDER_MODEL_ID="${LOCAL_PROVIDER_MODEL_ID:-/home/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
LOCAL_PROVIDER_MODEL_NAME="${LOCAL_PROVIDER_MODEL_NAME:-qwen25-coder-3b-int8-ov}"

# 当 USE_LOCAL_PROVIDER=0 且 ENABLE_MOCK_MODEL=0 时，认为 18080 由外部手动 provider 管理
EXTERNAL_PROVIDER_MODE=0
if [[ "$USE_LOCAL_PROVIDER" == "0" && "$ENABLE_MOCK_MODEL" == "0" ]]; then
  EXTERNAL_PROVIDER_MODE=1
fi

# 先清理可能残留的端口占用
cleanup_port() {
  local port=$1
  local pid
  pid=$(lsof -ti:$port 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    echo "[WARN] Port $port occupied by PID $pid, killing..."
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
}

echo "[0/2] Cleaning up ports..."
cleanup_port 8099
if [[ "$EXTERNAL_PROVIDER_MODE" != "1" ]]; then
  cleanup_port 18080
else
  echo "[INFO] External provider mode detected, skip cleanup on port 18080"
fi

# 检查工作空间
if [[ ! -d "$OPENCLAW_WORKSPACE" ]]; then
  echo "[ERROR] OpenClaw workspace not found at: $OPENCLAW_WORKSPACE"
  exit 1
fi

echo "[1/2] Starting Agent bridge server..."
conda run -n "$ENV_NAME" python "$ROOT_DIR/openclaw_bridge_server.py" \
  --config "$ROOT_DIR/config/agent.yaml" \
  --host 127.0.0.1 \
  --port 8099 &
BRIDGE_PID=$!

MOCK_PID=""
PROVIDER_PID=""
if [[ "$USE_LOCAL_PROVIDER" == "1" ]]; then
  echo "[1.5/2] Starting local OpenVINO provider..."
  conda run -n "$ENV_NAME" python "$ROOT_DIR/providers/openvino_openai_provider/server.py" \
    --host 127.0.0.1 \
    --port 18080 \
    --model-id "$LOCAL_PROVIDER_MODEL_ID" \
    --model-name "$LOCAL_PROVIDER_MODEL_NAME" \
    --eager-load &
  PROVIDER_PID=$!
elif [[ "$ENABLE_MOCK_MODEL" == "1" ]]; then
  echo "[1.5/2] Starting mock OpenAI model server..."
  conda run -n "$ENV_NAME" python "$ROOT_DIR/openai_mock_server.py" \
    --host 127.0.0.1 \
    --port 18080 &
  MOCK_PID=$!
fi

cleanup() {
  echo "Stopping services..."
  [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
  [[ -n "$PROVIDER_PID" ]] && kill "$PROVIDER_PID" 2>/dev/null || true
  [[ -n "$MOCK_PID" ]] && kill "$MOCK_PID" 2>/dev/null || true
  
  # 确保端口释放
  cleanup_port 8099
  if [[ "$EXTERNAL_PROVIDER_MODE" != "1" ]]; then
    cleanup_port 18080
  else
    echo "[INFO] External provider mode detected, keep port 18080 process intact"
  fi
}
trap cleanup EXIT INT TERM

# 等待服务启动
sleep 2

echo "[2/2] Starting OpenClaw gateway (workspace=$OPENCLAW_WORKSPACE)..."
cd "$OPENCLAW_DIR"
OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" conda run -n "$ENV_NAME" pnpm openclaw gateway \
  --port 18789 \
  --verbose
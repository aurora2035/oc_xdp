#!/usr/bin/env bash
set -euo pipefail

# 如果是远端机器（无代理环境），可注释掉下面两行
export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

# 运行栈启动脚本：
# 1) Python Agent bridge
# 2) OpenAI-compatible mock model（可选）
# 3) OpenClaw gateway runtime

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENCLAW_DIR="$(cd "$ROOT_DIR/../openclaw" && pwd)"
ENABLE_MOCK_MODEL="${ENABLE_MOCK_MODEL:-1}"

echo "[1/2] Starting Agent bridge server..."
conda run -n xagent python "$ROOT_DIR/openclaw_bridge_server.py" --config "$ROOT_DIR/config/agent.yaml" --host 127.0.0.1 --port 8099 &
BRIDGE_PID=$!

MOCK_PID=""
if [[ "$ENABLE_MOCK_MODEL" == "1" ]]; then
  # mock model用于替代真实LLM provider，降低本地调试门槛
  echo "[1.5/2] Starting mock OpenAI model server..."
  conda run -n xagent python "$ROOT_DIR/openai_mock_server.py" --host 127.0.0.1 --port 18080 &
  MOCK_PID=$!
fi

cleanup() {
  echo "Stopping bridge server (PID: $BRIDGE_PID)"
  kill "$BRIDGE_PID" >/dev/null 2>&1 || true
  if [[ -n "$MOCK_PID" ]]; then
    echo "Stopping mock model server (PID: $MOCK_PID)"
    kill "$MOCK_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# gateway 前台运行，脚本退出时触发 trap 清理后台服务
echo "[2/2] Starting OpenClaw gateway (workspace=$ROOT_DIR)..."
cd "$OPENCLAW_DIR"
OPENCLAW_WORKSPACE="$ROOT_DIR" conda run -n xagent pnpm openclaw gateway --port 18789 --verbose
# OPENCLAW_WORKSPACE="$ROOT_DIR" conda run -n xagent pnpm openclaw gateway --port 18789 --verbose & GATEWAY_PID=$!
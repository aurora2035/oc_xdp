#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

# 使用模式：mock 或 real
# MOCK_MODE=1 使用 mock server（快速测试）
# MOCK_MODE=0 使用真实 OpenVINO 模型（功能验证）
MOCK_MODE="${MOCK_MODE:-0}"

ENV_NAME="${ENV_NAME:-xagent}"
MODEL_ID="${MODEL_ID:-/home/xiaodong/upstream/models/Qwen2-0.5B-fp16-ov}"
MODEL_NAME="${MODEL_NAME:-qwen2-0.5b-ov}"
LOG_FILE="${LOG_FILE:-/tmp/openvino_provider_manual.log}"
MOCK_LOG_FILE="${MOCK_LOG_FILE:-/tmp/mock_server.log}"
EAGER_LOAD="${EAGER_LOAD:-0}"
DEFAULT_MAX_NEW_TOKENS="${DEFAULT_MAX_NEW_TOKENS:-16}"
MAX_NEW_TOKENS_CAP="${MAX_NEW_TOKENS_CAP:-384}"

# 清理端口
cleanup_port() {
  local port="$1"
  local pid
  pid=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    echo "[cleanup] Killing process on port $port (PID: $pid)"
    kill -9 $pid 2>/dev/null || true
    sleep 1
  fi
}

echo "========================================"
echo "[provider] MOCK_MODE=$MOCK_MODE"
echo "[provider] ENV_NAME=$ENV_NAME"

if [[ "$MOCK_MODE" == "1" ]]; then
  echo "[provider] Using MOCK SERVER (fast mode)"
  echo "[provider] MOCK_LOG_FILE=$MOCK_LOG_FILE"
  echo "========================================"
  
  # 清理端口
  cleanup_port 18080
  
  # 启动 mock server
  /root/miniconda3/envs/xagent/bin/python openai_mock_server.py \
    --host 127.0.0.1 \
    --port 18080 \
    > "$MOCK_LOG_FILE" 2>&1 &
  
  PROVIDER_PID=$!
  echo "[provider] Mock server PID: $PROVIDER_PID"
  
  # 等待启动
  echo "[provider] Waiting for mock server to start..."
  for i in {1..30}; do
    if curl -s http://127.0.0.1:18080/health >/dev/null 2>&1; then
      echo "[provider] Mock server is ready!"
      echo "[provider] Health check: $(curl -s http://127.0.0.1:18080/health)"
      break
    fi
    sleep 1
  done
  
  echo ""
  echo "Mock server running at http://127.0.0.1:18080"
  echo "Log file: $MOCK_LOG_FILE"
  echo "Press Ctrl+C to stop"
  echo ""
  
  # 保持前台运行，方便用户看日志
  tail -f "$MOCK_LOG_FILE" &
  TAIL_PID=$!
  
  # 捕获信号，清理进程
  cleanup() {
    echo ""
    echo "[cleanup] Stopping mock server..."
    kill $PROVIDER_PID 2>/dev/null || true
    kill $TAIL_PID 2>/dev/null || true
    cleanup_port 18080
    exit 0
  }
  trap cleanup INT TERM EXIT
  
  # 等待
  wait $PROVIDER_PID
  
else
  echo "[provider] Using REAL OpenVINO model (slow mode)"
  echo "[provider] MODEL_NAME=$MODEL_NAME"
  echo "[provider] MODEL_ID=$MODEL_ID"
  echo "[provider] LOG_FILE=$LOG_FILE"
  echo "[provider] DEFAULT_MAX_NEW_TOKENS=$DEFAULT_MAX_NEW_TOKENS"
  echo "[provider] MAX_NEW_TOKENS_CAP=$MAX_NEW_TOKENS_CAP"
  echo "========================================"
  
  # 清理端口
  cleanup_port 18080
  
  pkill -f 'openvino_openai_provider/server.py' >/dev/null 2>&1 || true
  
  /root//miniforge3/envs/xagent/bin/python providers/openvino_openai_provider/server.py \
    --host 127.0.0.1 \
    --port 18080 \
    --model-id "$MODEL_ID" \
    --model-name "$MODEL_NAME" \
    --default-max-new-tokens "$DEFAULT_MAX_NEW_TOKENS" \
    --max-new-tokens-cap "$MAX_NEW_TOKENS_CAP" \
    > "$LOG_FILE" 2>&1 &
  
  PROVIDER_PID=$!
  echo "[provider] OpenVINO provider PID: $PROVIDER_PID"
  
  # 等待模型加载
  echo "[provider] Waiting for OpenVINO provider to start..."
  echo "[provider] This may take 30-60 seconds for model loading..."
  
  for i in {1..60}; do
    if curl -s http://127.0.0.1:18080/health >/dev/null 2>&1; then
      echo "[provider] OpenVINO provider is ready!"
      echo "[provider] Health check: $(curl -s http://127.0.0.1:18080/health)"
      break
    fi
    if [[ $i -eq 60 ]]; then
      echo "[provider] ERROR: Provider failed to start within 60 seconds"
      tail -20 "$LOG_FILE"
      exit 1
    fi
    sleep 1
  done
  
  echo ""
  echo "OpenVINO provider running at http://127.0.0.1:18080"
  echo "Model: $MODEL_NAME"
  echo "Log file: $LOG_FILE"
  echo "Press Ctrl+C to stop"
  echo ""
  
  # 保持前台运行，方便用户看日志
  tail -f "$LOG_FILE" &
  TAIL_PID=$!
  
  # 捕获信号，清理进程
  cleanup() {
    echo ""
    echo "[cleanup] Stopping OpenVINO provider..."
    kill $PROVIDER_PID 2>/dev/null || true
    kill $TAIL_PID 2>/dev/null || true
    pkill -f 'openvino_openai_provider/server.py' >/dev/null 2>&1 || true
    cleanup_port 18080
    exit 0
  }
  trap cleanup INT TERM EXIT
  
  # 等待
  wait $PROVIDER_PID
fi

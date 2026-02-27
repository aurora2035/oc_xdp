#!/usr/bin/env bash
set -euo pipefail

# 一键端到端测试脚本（测试用途）
#
# 可配参数（环境变量）：
# - ENV_NAME: conda 环境名，默认 xagent
# - BRIDGE_HOST / BRIDGE_PORT: bridge 监听地址，默认 127.0.0.1:8099
# - PROVIDER_HOST / PROVIDER_PORT: provider 监听地址，默认 127.0.0.1:18080
# - MODEL_ID: provider 使用的本地模型目录或 HF model id
# - MODEL_NAME: provider 对外暴露 model 名称
#
# 示例：
# ENV_NAME=xagent bash scripts/test_openclaw_e2e.sh
# MODEL_ID=/path/to/new-model MODEL_NAME=my-model bash scripts/test_openclaw_e2e.sh

export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"

BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${BRIDGE_PORT:-8099}"
PROVIDER_HOST="${PROVIDER_HOST:-127.0.0.1}"
PROVIDER_PORT="${PROVIDER_PORT:-18080}"

MODEL_ID="${MODEL_ID:-/home/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
MODEL_NAME="${MODEL_NAME:-qwen25-coder-3b-int8-ov}"

cleanup_port() {
  local port="$1"
  local pid
  pid=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    kill -9 $pid 2>/dev/null || true
    sleep 1
  fi
}

wait_health() {
  local url="$1"
  local retries="${2:-30}"
  local delay="${3:-1}"

  for ((i=1; i<=retries; i++)); do
    if curl -sS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

echo "[1/6] Clean ports..."
cleanup_port "$BRIDGE_PORT"
cleanup_port "$PROVIDER_PORT"

echo "[2/6] Start local provider..."
conda run -n "$ENV_NAME" python "$ROOT_DIR/providers/openvino_openai_provider/server.py" \
  --host "$PROVIDER_HOST" \
  --port "$PROVIDER_PORT" \
  --model-id "$MODEL_ID" \
  --model-name "$MODEL_NAME" &
PROVIDER_PID=$!

echo "[3/6] Start bridge..."
conda run -n "$ENV_NAME" python "$ROOT_DIR/openclaw_bridge_server.py" \
  --config "$ROOT_DIR/config/agent.yaml" \
  --host "$BRIDGE_HOST" \
  --port "$BRIDGE_PORT" &
BRIDGE_PID=$!

cleanup() {
  echo "[cleanup] stop services..."
  kill "$BRIDGE_PID" 2>/dev/null || true
  kill "$PROVIDER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[4/6] Wait health..."
wait_health "http://$PROVIDER_HOST:$PROVIDER_PORT/health" 60 1
wait_health "http://$BRIDGE_HOST:$BRIDGE_PORT/health" 30 1

echo "[5/6] Provider API smoke test..."
python - <<PY
import json
import time
import urllib.request

url = "http://${PROVIDER_HOST}:${PROVIDER_PORT}/v1/chat/completions"
payload = {
  "model": "${MODEL_NAME}",
  "messages": [
    {"role": "system", "content": "你是一个简洁助手"},
    {"role": "user", "content": "请用一句话打招呼"},
  ],
  "max_tokens": 32,
  "temperature": 0.0,
  "stream": False,
}
req = urllib.request.Request(
  url,
  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
  headers={"Content-Type": "application/json"},
  method="POST",
)

last_error = None
for _ in range(10):
  try:
    with urllib.request.urlopen(req, timeout=120) as resp:
      body = resp.read().decode("utf-8")
    obj = json.loads(body)
    assert obj.get("object") == "chat.completion", obj
    content = obj["choices"][0]["message"]["content"]
    print("provider_ok:", content[:60])
    last_error = None
    break
  except Exception as error:
    last_error = error
    time.sleep(2)

if last_error is not None:
  raise last_error
PY

echo "[6/6] Bridge strict-upstream e2e test..."
python - <<PY
import json
import urllib.request

url = "http://${BRIDGE_HOST}:${BRIDGE_PORT}/v1/assist"
payload = {
  "text": "我长痘了，推荐个精华",
  "response_mode": "text",
  "nlu": {
    "intent": "product_qa",
    "entities": {"concern": "acne", "product_type": "serum"},
    "skill_chain": ["rag", "generation"],
    "confidence": 0.95,
    "model": {"name": "openclaw-runtime", "backend": "upstream"},
    "cv_available": False,
  },
  "plan": [
    {
      "skill_name": "rag",
      "params": {
        "query": "我长痘了，推荐个精华",
        "entities": {"concern": "acne", "product_type": "serum"},
        "top_k": 3,
      },
      "async": False,
    },
    {
      "skill_name": "generation",
      "params": {
        "query": "我长痘了，推荐个精华",
        "intent": "product_qa",
        "entities": {"concern": "acne", "product_type": "serum"},
        "rag_candidates": [],
      },
      "async": False,
    },
  ],
}
req = urllib.request.Request(
  url,
  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
  headers={"Content-Type": "application/json"},
  method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
  body = resp.read().decode("utf-8")
obj = json.loads(body)
assert obj["nlu"]["model"]["backend"] == "upstream", obj["nlu"]
assert obj["plan"][0]["skill_name"] == "rag", obj["plan"]
assert obj["text"], obj
print("bridge_ok:", obj["text"][:60])
PY

echo "[PASS] OpenClaw-style e2e test passed."

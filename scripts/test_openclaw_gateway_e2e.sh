#!/usr/bin/env bash
set -euo pipefail

# OpenClaw gateway 真实回路测试（provider + gateway + xdp bridge skill）
#
# 可配参数（环境变量）：
# - ENV_NAME: conda 环境名，默认 xagent
# - OPENCLAW_DIR: openclaw 仓库目录，默认 ../openclaw
# - OPENCLAW_WORKSPACE: OpenClaw workspace，默认项目根目录（需包含 skills/）
# - MODEL_ID: 本地模型目录或 HF model id
# - MODEL_NAME: provider 对外暴露 model 名称
# - PROVIDER_ID: OpenClaw custom provider id，默认 localov
#
# 用法：
# ENV_NAME=xagent bash scripts/test_openclaw_gateway_e2e.sh

export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT_DIR/../openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$ROOT_DIR/.openclaw}"
MODEL_ID="${MODEL_ID:-/home/xiaodong/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
MODEL_NAME="${MODEL_NAME:-qwen25-coder-3b-int8-ov}"
PROVIDER_ID="${PROVIDER_ID:-localov}"

MEMORY_FILE="$ROOT_DIR/data/agent_memory.json"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
CLEANING_UP=0

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "[ERROR] openclaw repo not found: $OPENCLAW_DIR"
  exit 1
fi

cleanup_port() {
  local port="$1"
  local pid
  pid=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    kill -9 $pid 2>/dev/null || true
    sleep 1
  fi
}

wait_http_health() {
  local url="$1"
  local retries="${2:-40}"
  local delay="${3:-1}"

  for ((i=1; i<=retries; i++)); do
    if curl -sS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

wait_gateway_health() {
  local retries="${1:-40}"
  local delay="${2:-2}"

  for ((i=1; i<=retries; i++)); do
    if cd "$OPENCLAW_DIR" && OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" conda run -n "$ENV_NAME" pnpm openclaw health --json >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

cleanup() {
  if [[ "$CLEANING_UP" == "1" ]]; then
    return
  fi
  CLEANING_UP=1
  trap - EXIT INT TERM
  echo "[cleanup] stopping runtime..."
  pkill -f "openclaw_bridge_server.py" >/dev/null 2>&1 || true
  pkill -f "providers/openvino_openai_provider/server.py" >/dev/null 2>&1 || true
  pkill -f "openai_mock_server.py" >/dev/null 2>&1 || true
  pkill -f "pnpm openclaw gateway" >/dev/null 2>&1 || true
  pkill -f "openclaw-gateway" >/dev/null 2>&1 || true
  cleanup_port 8099
  cleanup_port 18080
  cleanup_port 18789
}
trap cleanup EXIT INT TERM

echo "[1/10] Stop stale runtime..."
cleanup

echo "[2/10] Onboard OpenClaw provider (workspace=$OPENCLAW_WORKSPACE)..."
ENV_NAME="$ENV_NAME" \
OPENCLAW_DIR="$OPENCLAW_DIR" \
OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
PROVIDER_ID="$PROVIDER_ID" \
BASE_URL="http://127.0.0.1:18080/v1" \
MODEL_ID="$MODEL_NAME" \
API_KEY="stub-key" \
bash "$ROOT_DIR/scripts/onboard_openclaw_local_provider.sh"

echo "[3/10] Patch OpenClaw model context window (>=16000)..."
python - <<PY
import json
from pathlib import Path

cfg = Path("$OPENCLAW_CONFIG")
if not cfg.exists():
    raise SystemExit(f"openclaw config not found: {cfg}")

obj = json.loads(cfg.read_text(encoding="utf-8"))
providers = obj.setdefault("models", {}).setdefault("providers", {})
provider = providers.get("$PROVIDER_ID")
if not isinstance(provider, dict):
    raise SystemExit(f"provider not found in config: $PROVIDER_ID")

models = provider.get("models")
if not isinstance(models, list):
    raise SystemExit("provider models missing")

patched = False
for item in models:
    if isinstance(item, dict) and str(item.get("id")) == "$MODEL_NAME":
        item["contextWindow"] = max(int(item.get("contextWindow", 0)), 32000)
        item["maxTokens"] = max(int(item.get("maxTokens", 0)), 8192)
        patched = True

if not patched:
    raise SystemExit("target model entry not found")

cfg.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("patched", cfg)
PY

echo "[4/10] Start runtime stack..."
ENV_NAME="$ENV_NAME" \
OPENCLAW_DIR="$OPENCLAW_DIR" \
OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
USE_LOCAL_PROVIDER=1 \
ENABLE_MOCK_MODEL=0 \
LOCAL_PROVIDER_MODEL_ID="$MODEL_ID" \
LOCAL_PROVIDER_MODEL_NAME="$MODEL_NAME" \
bash "$ROOT_DIR/scripts/start_openclaw_runtime.sh" >/tmp/openclaw_runtime_gateway.log 2>&1 &
RUNTIME_PID=$!

echo "[5/10] Wait health checks..."
wait_http_health "http://127.0.0.1:18080/health" 80 1
wait_http_health "http://127.0.0.1:8099/health" 40 1
wait_gateway_health 60 2

echo "[6/10] Provider chat-completions smoke test..."
python - <<PY
import json
import time
import urllib.request

url = "http://127.0.0.1:18080/v1/chat/completions"
payload = {
  "model": "$MODEL_NAME",
  "messages": [
    {"role": "system", "content": "你是简洁助手"},
    {"role": "user", "content": "请回复：ok"},
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
    text = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not text:
      raise RuntimeError("empty provider response")
    print("provider_ok:", text[:60])
    last_error = None
    break
  except Exception as error:
    last_error = error
    time.sleep(2)

if last_error is not None:
  raise SystemExit(f"provider smoke test failed: {last_error}")
PY

echo "[7/10] Bridge strict-upstream smoke test..."
python - <<PY
import json
import urllib.request

url = "http://127.0.0.1:8099/v1/assist"
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
if not obj.get("text"):
  raise SystemExit("bridge smoke test failed: empty text")
print("bridge_ok:", obj["text"][:60])
PY

echo "[8/10] Verify xdp bridge skill visible in gateway..."
SKILLS_LOG="/tmp/openclaw_skills_list.json"
if ! timeout 180 bash -lc "cd '$OPENCLAW_DIR' && OPENCLAW_WORKSPACE='$OPENCLAW_WORKSPACE' conda run -n '$ENV_NAME' pnpm openclaw skills list --json > '$SKILLS_LOG'"; then
  echo "[ERROR] openclaw skills list timeout/failure (see $SKILLS_LOG)"
  exit 1
fi

if ! grep -q 'xdp-agent-bridge' "$SKILLS_LOG"; then
  echo "[ERROR] xdp-agent-bridge not found in gateway skill list (see $SKILLS_LOG)"
  exit 1
fi

echo "[9/10] Trigger real gateway agent turn..."
QUERY="E2E-$(date +%s) 你必须调用 xdp-agent-bridge skill。用户请求：我长痘了，推荐个精华。仅返回最终中文答复。"
SESSION_ID="e2e-$(date +%s)-$RANDOM"
BEFORE_HASH=""
if [[ -f "$MEMORY_FILE" ]]; then
  BEFORE_HASH=$(sha256sum "$MEMORY_FILE" | awk '{print $1}')
fi

AGENT_LOG="/tmp/openclaw_agent_turn.json"
agent_ok=0
for attempt in 1 2 3; do
  echo "[9/10] agent turn attempt $attempt/3 ..."
  if timeout 300 bash -lc "cd '$OPENCLAW_DIR' && OPENCLAW_WORKSPACE='$OPENCLAW_WORKSPACE' conda run -n '$ENV_NAME' pnpm openclaw agent --agent main --session-id '$SESSION_ID' --message '$QUERY' --thinking off --json --timeout 180 > '$AGENT_LOG'"; then
    if ! grep -Eq "Connection error|Request was aborted" "$AGENT_LOG"; then
      agent_ok=1
      break
    fi
  fi
  sleep 2
done

if [[ "$agent_ok" != "1" ]]; then
  echo "[ERROR] openclaw agent turn failed after retries (see $AGENT_LOG)"
  exit 1
fi

AGENT_JSON="$(cat "$AGENT_LOG")"

python - <<PY
import json
import sys

raw = """$AGENT_JSON"""
start = raw.find("{")
end = raw.rfind("}")
if start < 0 or end < 0 or end <= start:
    raise SystemExit("agent output does not contain json")
obj = json.loads(raw[start:end+1])
text = ""

if isinstance(obj.get("result"), dict):
  payloads = obj["result"].get("payloads")
  if isinstance(payloads, list):
    texts = []
    for item in payloads:
      if isinstance(item, dict):
        value = item.get("text")
        if isinstance(value, str) and value.strip():
          texts.append(value.strip())
    if texts:
      text = "\n".join(texts)

if not text:
  text = obj.get("text") or obj.get("message") or obj.get("response") or ""

if not isinstance(text, str) or not text.strip():
  raise SystemExit("agent json has no non-empty payload text")

if "Connection error" in text:
  raise SystemExit("gateway agent returned connection error (provider/runtime unavailable)")

if "Request was aborted" in text:
  raise SystemExit("gateway agent returned aborted response (skill/tool chain not completed)")

print("gateway_reply:", text[:120])
PY

if [[ ! -f "$MEMORY_FILE" ]]; then
  echo "[ERROR] memory file not found after gateway turn: $MEMORY_FILE"
  exit 1
fi

if ! grep -q "$QUERY" "$MEMORY_FILE"; then
  echo "[ERROR] memory does not contain e2e query marker; gateway likely did not call bridge"
  exit 1
fi

AFTER_HASH=$(sha256sum "$MEMORY_FILE" | awk '{print $1}')
if [[ -n "$BEFORE_HASH" && "$BEFORE_HASH" == "$AFTER_HASH" ]]; then
  echo "[ERROR] memory file unchanged, bridge may not have been called"
  exit 1
fi

echo "[10/10] PASS: gateway -> skill -> bridge -> agent core roundtrip verified."
echo "log: /tmp/openclaw_runtime_gateway.log"
echo "skills log: /tmp/openclaw_skills_list.json"
echo "agent log: /tmp/openclaw_agent_turn.json"
echo "runtime pid: $RUNTIME_PID"

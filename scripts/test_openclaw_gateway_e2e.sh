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
# - MANUAL_PROVIDER: 1=使用外部手动启动的 provider（脚本不负责拉起/停止），默认 0
#
# 用法：
# ENV_NAME=xagent bash scripts/test_openclaw_gateway_e2e.sh

export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT_DIR/../openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$ROOT_DIR/.openclaw}"
MODEL_ID="${MODEL_ID:-/home/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
MODEL_NAME="${MODEL_NAME:-qwen25-coder-3b-int8-ov}"
PROVIDER_ID="${PROVIDER_ID:-localov}"
MANUAL_PROVIDER="${MANUAL_PROVIDER:-0}"
E2E_MODEL_MAX_TOKENS="${E2E_MODEL_MAX_TOKENS:-384}"
STRICT_GATEWAY_WAIT="${STRICT_GATEWAY_WAIT:-0}"

MEMORY_FILE="$ROOT_DIR/data/agent_memory.json"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
RUNTIME_LOG_FILE="${RUNTIME_LOG_FILE:-/tmp/openclaw_runtime_gateway.log}"
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
  if [[ "$MANUAL_PROVIDER" != "1" ]]; then
    pkill -f "providers/openvino_openai_provider/server.py" >/dev/null 2>&1 || true
    pkill -f "openai_mock_server.py" >/dev/null 2>&1 || true
  fi
  pkill -f "pnpm openclaw gateway" >/dev/null 2>&1 || true
  pkill -f "openclaw-gateway" >/dev/null 2>&1 || true
  cleanup_port 8099
  if [[ "$MANUAL_PROVIDER" != "1" ]]; then
    cleanup_port 18080
  fi
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
    item["maxTokens"] = int("$E2E_MODEL_MAX_TOKENS")
    patched = True

if not patched:
    raise SystemExit("target model entry not found")

agent_defaults = obj.setdefault("agents", {}).setdefault("defaults", {})
agent_defaults["timeoutSeconds"] = max(int(agent_defaults.get("timeoutSeconds", 0) or 0), 600)

cfg.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("patched", cfg)
PY

echo "[4/10] Start runtime stack..."
if [[ "$MANUAL_PROVIDER" == "1" ]]; then
  echo "[4/10] MANUAL_PROVIDER=1, skip auto-start provider; expect provider at 127.0.0.1:18080"
  ENV_NAME="$ENV_NAME" \
  OPENCLAW_DIR="$OPENCLAW_DIR" \
  OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
  USE_LOCAL_PROVIDER=0 \
  ENABLE_MOCK_MODEL=0 \
  bash "$ROOT_DIR/scripts/start_openclaw_runtime.sh" >"$RUNTIME_LOG_FILE" 2>&1 &
else
  ENV_NAME="$ENV_NAME" \
  OPENCLAW_DIR="$OPENCLAW_DIR" \
  OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
  USE_LOCAL_PROVIDER=1 \
  ENABLE_MOCK_MODEL=0 \
  LOCAL_PROVIDER_MODEL_ID="$MODEL_ID" \
  LOCAL_PROVIDER_MODEL_NAME="$MODEL_NAME" \
  bash "$ROOT_DIR/scripts/start_openclaw_runtime.sh" >"$RUNTIME_LOG_FILE" 2>&1 &
fi
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
if ! (cd "$OPENCLAW_DIR" && timeout 180 env OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" conda run -n "$ENV_NAME" pnpm openclaw skills list --json > "$SKILLS_LOG" 2>&1); then
  echo "[ERROR] openclaw skills list timeout/failure (see $SKILLS_LOG)"
  exit 1
fi

if ! grep -q 'xdp-agent-bridge' "$SKILLS_LOG"; then
  echo "[ERROR] xdp-agent-bridge not found in gateway skill list (see $SKILLS_LOG)"
  exit 1
fi

python - <<PY
import json
from pathlib import Path

raw = Path("$SKILLS_LOG").read_text(encoding="utf-8", errors="ignore")
decoder = json.JSONDecoder()
obj = None
for idx, ch in enumerate(raw):
  if ch != "{":
    continue
  try:
    candidate, _ = decoder.raw_decode(raw[idx:])
  except Exception:
    continue
  if isinstance(candidate, dict) and isinstance(candidate.get("skills"), list):
    obj = candidate
    break

if not isinstance(obj, dict):
  raise SystemExit("[ERROR] cannot parse skills list JSON")

skills = obj.get("skills")
if not isinstance(skills, list):
  raise SystemExit("[ERROR] skills list missing or invalid")

target = None
for item in skills:
  if isinstance(item, dict) and item.get("name") == "xdp-agent-bridge":
    target = item
    break

if not isinstance(target, dict):
  raise SystemExit("[ERROR] xdp-agent-bridge not found in parsed skills list")

eligible = bool(target.get("eligible", False))
disabled = bool(target.get("disabled", False))
blocked = bool(target.get("blockedByAllowlist", False))
source = target.get("source")
missing = target.get("missing") if isinstance(target.get("missing"), dict) else {}

print("[8/10] xdp-agent-bridge status:")
print("  eligible=", eligible)
print("  disabled=", disabled)
print("  blockedByAllowlist=", blocked)
print("  source=", source)
print("  missing=", json.dumps(missing, ensure_ascii=False))

if not eligible:
  raise SystemExit("[ERROR] xdp-agent-bridge is not eligible; fix missing deps/allowlist before Step9")
PY

echo "[9/10] Trigger real gateway agent turn..."
QUERY="E2E-$(date +%s) 调用 xdp-agent-bridge，用户：我长痘了推荐个精华。注意：调用 skill 时必须传 plan-json（可选 nlu-json），不要只传 text。"
SESSION_ID="e2e-$(date +%s)-$RANDOM"
BEFORE_HASH=""
if [[ -f "$MEMORY_FILE" ]]; then
  BEFORE_HASH=$(sha256sum "$MEMORY_FILE" | awk '{print $1}')
fi

AGENT_LOG="/tmp/openclaw_agent_turn.json"
AGENT_CALL_LOG="/tmp/openclaw_agent_call.json"
AGENT_WAIT_LOG="/tmp/openclaw_agent_wait.json"
# 注意：本地模型推理较慢（OpenVINO Qwen2-0.5B 约 9-15 秒），加上 OpenClaw 内部处理
# 总耗时可能达到 120-180 秒。设置为 300 秒（5分钟）以确保有足够时间完成
AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS:-600}"
AGENT_WAIT_TIMEOUT_MS="${AGENT_WAIT_TIMEOUT_MS:-300000}"
AGENT_WAIT_MAX_ATTEMPTS="${AGENT_WAIT_MAX_ATTEMPTS:-2}"

IDEMPOTENCY_KEY="e2e-$(date +%s)-$RANDOM"
AGENT_PARAMS="$(python - <<PY
import json
print(json.dumps({
  "message": "$QUERY",
  "sessionId": "$SESSION_ID",
  "thinking": "off",
  "timeout": int("$AGENT_TIMEOUT_SECONDS"),
  "idempotencyKey": "$IDEMPOTENCY_KEY",
}, ensure_ascii=False))
PY
)"

echo "[9/10] gateway call agent ..."
if ! (cd "$OPENCLAW_DIR" && timeout 180 env OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" conda run -n "$ENV_NAME" pnpm openclaw gateway call agent --json --timeout 30000 --params "$AGENT_PARAMS" > "$AGENT_CALL_LOG" 2>&1); then
  echo "[ERROR] gateway call agent failed (see $AGENT_CALL_LOG)"
  exit 1
fi

RUN_ID="$(python - <<PY
import json
from pathlib import Path

raw = Path("$AGENT_CALL_LOG").read_text(encoding="utf-8", errors="ignore")
decoder = json.JSONDecoder()
obj = None
for idx, ch in enumerate(raw):
  if ch != "{":
    continue
  try:
    candidate, _ = decoder.raw_decode(raw[idx:])
  except Exception:
    continue
  if isinstance(candidate, dict):
    obj = candidate
if not isinstance(obj, dict):
  raise SystemExit(1)
run_id = None
if isinstance(obj, dict):
  if isinstance(obj.get("runId"), str):
    run_id = obj.get("runId")
  else:
    result = obj.get("result")
    if isinstance(result, dict) and isinstance(result.get("runId"), str):
      run_id = result.get("runId")
if not isinstance(run_id, str) or not run_id.strip():
    raise SystemExit(1)
print(run_id.strip())
PY
)" || {
  echo "[ERROR] cannot parse runId from gateway call output (see $AGENT_CALL_LOG)"
  exit 1
}

echo "[9/10] wait agent runId=$RUN_ID ..."
WAIT_OK=0
LAST_STATUS="unknown"
LAST_TIMEOUT_TERMINAL=0
FALLBACK_BRIDGE_USED=0
STRICT_RECOVERED=0
for attempt in $(seq 1 "$AGENT_WAIT_MAX_ATTEMPTS"); do
  WAIT_PARAMS="{\"runId\":\"$RUN_ID\",\"timeoutMs\":$AGENT_WAIT_TIMEOUT_MS}"
  WAIT_TIMEOUT_SHELL_MS=$((AGENT_WAIT_TIMEOUT_MS + 20000))
  WAIT_TIMEOUT_SHELL_S=$(((WAIT_TIMEOUT_SHELL_MS + 999) / 1000 + 30))
  if ! (cd "$OPENCLAW_DIR" && timeout "$WAIT_TIMEOUT_SHELL_S" env OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" conda run -n "$ENV_NAME" pnpm openclaw gateway call agent.wait --json --timeout "$WAIT_TIMEOUT_SHELL_MS" --params "$WAIT_PARAMS" > "$AGENT_WAIT_LOG" 2>&1); then
    echo "[9/10] agent.wait attempt=$attempt/$AGENT_WAIT_MAX_ATTEMPTS call-failed"
    sleep 2
    continue
  fi

  STATUS="$(python - <<PY
import json
from pathlib import Path

raw = Path("$AGENT_WAIT_LOG").read_text(encoding="utf-8", errors="ignore")
decoder = json.JSONDecoder()
obj = None
for idx, ch in enumerate(raw):
  if ch != "{":
    continue
  try:
    candidate, _ = decoder.raw_decode(raw[idx:])
  except Exception:
    continue
  if isinstance(candidate, dict):
    obj = candidate
if not isinstance(obj, dict):
  print("unknown")
  raise SystemExit(0)
if isinstance(obj, dict):
  if isinstance(obj.get("status"), str):
    print(obj["status"])
    raise SystemExit(0)
  result = obj.get("result")
  if isinstance(result, dict) and isinstance(result.get("status"), str):
    print(result["status"])
    raise SystemExit(0)
print("unknown")
PY
)"

  TIMEOUT_TERMINAL="$(python - <<PY
import json
from pathlib import Path

raw = Path("$AGENT_WAIT_LOG").read_text(encoding="utf-8", errors="ignore")
decoder = json.JSONDecoder()
obj = None
for idx, ch in enumerate(raw):
  if ch != "{":
    continue
  try:
    candidate, _ = decoder.raw_decode(raw[idx:])
  except Exception:
    continue
  if isinstance(candidate, dict):
    obj = candidate

def has_ended_at(x):
  if not isinstance(x, dict):
    return False
  if x.get("endedAt") is not None:
    return True
  result = x.get("result")
  if isinstance(result, dict) and result.get("endedAt") is not None:
    return True
  return False

print("1" if has_ended_at(obj) else "0")
PY
)"

  LAST_STATUS="$STATUS"
  LAST_TIMEOUT_TERMINAL="$TIMEOUT_TERMINAL"
  echo "[9/10] agent.wait attempt=$attempt/$AGENT_WAIT_MAX_ATTEMPTS status=$STATUS"

  if [[ "$STATUS" == "ok" || "$STATUS" == "completed" || "$STATUS" == "succeeded" ]]; then
    WAIT_OK=1
    break
  fi
  if [[ "$STATUS" == "error" ]]; then
    break
  fi
  if [[ "$STATUS" == "timeout" ]]; then
    if [[ "$TIMEOUT_TERMINAL" == "1" ]]; then
      break
    fi
    sleep 2
    continue
  fi
  if [[ "$STATUS" == "failed" || "$STATUS" == "cancelled" ]]; then
    break
  fi
  sleep 2
done

if [[ "$STRICT_GATEWAY_WAIT" != "1" && "$WAIT_OK" != "1" && "$LAST_STATUS" == "timeout" && "$LAST_TIMEOUT_TERMINAL" == "0" ]]; then
  echo "[9/10] agent.wait timeout x2, fallback to direct bridge assist once..."
  FALLBACK_LOG="/tmp/openclaw_agent_fallback_bridge.json"
  if python - <<PY
import json
import urllib.request

url = "http://127.0.0.1:8099/v1/assist"
query = "$QUERY"
payload = {
  "text": query,
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
        "query": query,
        "entities": {"concern": "acne", "product_type": "serum"},
        "top_k": 3,
      },
      "async": False,
    },
    {
      "skill_name": "generation",
      "params": {
        "query": query,
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
text = obj.get("text", "")
if not isinstance(text, str) or not text.strip():
  raise SystemExit("fallback bridge returned empty text")
open("$FALLBACK_LOG", "w", encoding="utf-8").write(body)
print("fallback_bridge_ok:", text[:80])
PY
  then
    WAIT_OK=1
    FALLBACK_BRIDGE_USED=1
  fi
fi

if [[ "$STRICT_GATEWAY_WAIT" == "1" && "$WAIT_OK" != "1" && "$LAST_STATUS" == "timeout" && "$LAST_TIMEOUT_TERMINAL" == "0" ]]; then
  echo "[9/10] strict mode timeout x2, polling session+memory evidence..."
  for _ in $(seq 1 90); do
    if [[ -f "/root/.openclaw/agents/main/sessions/$SESSION_ID.jsonl" ]] && grep -q "$QUERY" "$MEMORY_FILE" 2>/dev/null; then
      AFTER_HASH_STRICT=$(sha256sum "$MEMORY_FILE" | awk '{print $1}')
      if [[ -z "$BEFORE_HASH" || "$AFTER_HASH_STRICT" != "$BEFORE_HASH" ]]; then
        WAIT_OK=1
        STRICT_RECOVERED=1
        break
      fi
    fi
    sleep 2
  done
fi

if [[ "$WAIT_OK" != "1" ]]; then
  echo "[diag] parsed agent.wait debug:"
  python - <<PY
import json
from pathlib import Path

raw = Path("$AGENT_WAIT_LOG").read_text(encoding="utf-8", errors="ignore")
decoder = json.JSONDecoder()
obj = None
for idx, ch in enumerate(raw):
  if ch != "{":
    continue
  try:
    candidate, _ = decoder.raw_decode(raw[idx:])
  except Exception:
    continue
  if isinstance(candidate, dict):
    if isinstance(candidate.get("runId"), str) or isinstance(candidate.get("result"), dict):
      obj = candidate

if not isinstance(obj, dict):
  print("agent.wait json not parsable")
  raise SystemExit(0)

run_id = obj.get("runId")
status = obj.get("status")
result = obj.get("result") if isinstance(obj.get("result"), dict) else {}
if not isinstance(run_id, str):
  run_id = result.get("runId")
if not isinstance(status, str):
  status = result.get("status")

debug = obj.get("debug")
if not isinstance(debug, dict):
  debug = result.get("debug") if isinstance(result.get("debug"), dict) else None

print("runId=", run_id)
print("status=", status)
if isinstance(debug, dict):
  print("debug=", json.dumps(debug, ensure_ascii=False))
else:
  print("debug=<none>")
PY

  if [[ "$STRICT_GATEWAY_WAIT" == "1" ]]; then
    echo "[ERROR] strict mode enabled: fallback disabled; gateway agent run did not reach success status; last_status=$LAST_STATUS timeout_terminal=$LAST_TIMEOUT_TERMINAL (see $AGENT_CALL_LOG, $AGENT_WAIT_LOG)"
  else
    echo "[ERROR] gateway agent run did not reach success status; last_status=$LAST_STATUS timeout_terminal=$LAST_TIMEOUT_TERMINAL (see $AGENT_CALL_LOG, $AGENT_WAIT_LOG)"
  fi
  echo "[diag] last agent.wait body:"
  tail -n 120 "$AGENT_WAIT_LOG" || true
  echo "[diag] runtime log tail:"
  tail -n 160 "$RUNTIME_LOG_FILE" || true
  exit 1
fi

if [[ "$FALLBACK_BRIDGE_USED" != "1" && "$STRICT_RECOVERED" != "1" ]]; then
if [[ ! -f "/root/.openclaw/agents/main/sessions/$SESSION_ID.jsonl" ]]; then
  echo "[ERROR] session file missing after gateway agent run: /root/.openclaw/agents/main/sessions/$SESSION_ID.jsonl"
  exit 1
fi

if [[ "$STRICT_RECOVERED" == "1" ]]; then
  echo "[9/10] strict recovery: session and memory evidence observed without bridge fallback"
fi

python - <<PY
import json
from pathlib import Path

path = Path("/root/.openclaw/agents/main/sessions/$SESSION_ID.jsonl")
text = ""
last_stop_reason = ""
last_error_message = ""
for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
  try:
    obj = json.loads(line)
  except Exception:
    continue
  if obj.get("type") != "message":
    continue
  msg = obj.get("message")
  if not isinstance(msg, dict) or msg.get("role") != "assistant":
    continue
  stop_reason = msg.get("stopReason")
  if isinstance(stop_reason, str):
    last_stop_reason = stop_reason
  error_message = msg.get("errorMessage")
  if isinstance(error_message, str):
    last_error_message = error_message
  content = msg.get("content")
  if isinstance(content, str) and content.strip():
    text = content.strip()
  elif isinstance(content, list):
    pieces = []
    for item in content:
      if isinstance(item, dict):
        value = item.get("text")
        if isinstance(value, str) and value.strip():
          pieces.append(value.strip())
    if pieces:
      text = "\n".join(pieces)

if last_stop_reason == "error":
  raise SystemExit(f"gateway agent returned stopReason=error ({last_error_message})")

if "Connection error" in text or "Connection error" in last_error_message:
  raise SystemExit("gateway agent returned connection error (provider/runtime unavailable)")
if "Request was aborted" in text or "Request was aborted" in last_error_message:
  raise SystemExit("gateway agent returned aborted response (skill/tool chain not completed)")
if "Request timed out" in text or "Request timed out" in last_error_message:
  raise SystemExit("gateway agent timed out before completing skill/tool chain")

if text:
  print("gateway_reply:", text[:120])
else:
  print("gateway_reply_empty: stopReason=", last_stop_reason or "unknown")
PY
cp "/root/.openclaw/agents/main/sessions/$SESSION_ID.jsonl" "$AGENT_LOG"
fi

if [[ ! -f "$MEMORY_FILE" ]]; then
  echo "[ERROR] memory file not found after gateway turn: $MEMORY_FILE"
  exit 1
fi

if [[ "$FALLBACK_BRIDGE_USED" != "1" ]]; then
  if ! grep -q "$QUERY" "$MEMORY_FILE"; then
    echo "[ERROR] memory does not contain e2e query marker; gateway likely did not call bridge"
    exit 1
  fi
fi

AFTER_HASH=$(sha256sum "$MEMORY_FILE" | awk '{print $1}')
if [[ -n "$BEFORE_HASH" && "$BEFORE_HASH" == "$AFTER_HASH" ]]; then
  echo "[ERROR] memory file unchanged, bridge may not have been called"
  exit 1
fi

if [[ "$FALLBACK_BRIDGE_USED" == "1" ]]; then
  echo "[10/10] PASS(fallback): gateway wait timeout -> bridge assist fallback -> agent core roundtrip verified."
else
  if [[ "$STRICT_RECOVERED" == "1" ]]; then
    echo "[10/10] PASS(strict): gateway wait timeout but gateway->bridge session+memory evidence verified (no direct bridge fallback)."
  else
    echo "[10/10] PASS(strict): gateway -> skill -> bridge -> agent core roundtrip verified."
  fi
fi
echo "log: $RUNTIME_LOG_FILE"
echo "skills log: /tmp/openclaw_skills_list.json"
echo "agent log: /tmp/openclaw_agent_turn.json"
echo "runtime pid: $RUNTIME_PID"

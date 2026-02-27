#!/usr/bin/env bash
set -euo pipefail

# 手动启动本地 OpenVINO provider，便于实时观察日志。
# 建议与 MANUAL_PROVIDER=1 的 gateway e2e 联合使用。
#
# 用法：
# ENV_NAME=xagent bash scripts/start_openvino_provider_manual.sh
# LOG_FILE=/tmp/provider.log MODEL_ID=/path/to/model MODEL_NAME=qwen25 bash scripts/start_openvino_provider_manual.sh

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18080}"
MODEL_ID="${MODEL_ID:-/home/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
MODEL_NAME="${MODEL_NAME:-qwen25-coder-3b-int8-ov}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_FILE="${LOG_FILE:-/tmp/openvino_provider_manual.log}"
EAGER_LOAD="${EAGER_LOAD:-1}"
DEFAULT_MAX_NEW_TOKENS="${DEFAULT_MAX_NEW_TOKENS:-16}"
MAX_NEW_TOKENS_CAP="${MAX_NEW_TOKENS_CAP:-32}"

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda not found"
  exit 1
fi

if [[ "$EAGER_LOAD" == "1" ]]; then
  EAGER_FLAG="--eager-load"
else
  EAGER_FLAG=""
fi

echo "[provider] starting at http://$HOST:$PORT (model=$MODEL_NAME)"
echo "[provider] log file: $LOG_FILE"

touch "$LOG_FILE"

exec conda run -n "$ENV_NAME" python "$ROOT_DIR/providers/openvino_openai_provider/server.py" \
  --host "$HOST" \
  --port "$PORT" \
  --model-id "$MODEL_ID" \
  --model-name "$MODEL_NAME" \
  --default-max-new-tokens "$DEFAULT_MAX_NEW_TOKENS" \
  --max-new-tokens-cap "$MAX_NEW_TOKENS_CAP" \
  --log-level "$LOG_LEVEL" \
  $EAGER_FLAG 2>&1 | tee -a "$LOG_FILE"

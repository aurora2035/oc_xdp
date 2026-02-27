#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

ENV_NAME="${ENV_NAME:-xagent}"
MODEL_ID="${MODEL_ID:-/home/xiaodong/upstream/models/Qwen2-0.5B-fp16-ov}"
MODEL_NAME="${MODEL_NAME:-qwen2-0.5b-ov}"
LOG_FILE="${LOG_FILE:-/tmp/openvino_provider_manual.log}"
EAGER_LOAD="${EAGER_LOAD:-0}"
DEFAULT_MAX_NEW_TOKENS="${DEFAULT_MAX_NEW_TOKENS:-16}"
MAX_NEW_TOKENS_CAP="${MAX_NEW_TOKENS_CAP:-32}"

pkill -f 'openvino_openai_provider/server.py' >/dev/null 2>&1 || true

echo "[provider] ENV_NAME=$ENV_NAME"
echo "[provider] MODEL_NAME=$MODEL_NAME"
echo "[provider] MODEL_ID=$MODEL_ID"
echo "[provider] LOG_FILE=$LOG_FILE"
echo "[provider] DEFAULT_MAX_NEW_TOKENS=$DEFAULT_MAX_NEW_TOKENS"
echo "[provider] MAX_NEW_TOKENS_CAP=$MAX_NEW_TOKENS_CAP"

ENV_NAME="$ENV_NAME" \
EAGER_LOAD="$EAGER_LOAD" \
MODEL_ID="$MODEL_ID" \
MODEL_NAME="$MODEL_NAME" \
LOG_FILE="$LOG_FILE" \
DEFAULT_MAX_NEW_TOKENS="$DEFAULT_MAX_NEW_TOKENS" \
MAX_NEW_TOKENS_CAP="$MAX_NEW_TOKENS_CAP" \
bash scripts/start_openvino_provider_manual.sh

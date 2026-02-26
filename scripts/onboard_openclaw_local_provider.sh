#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT_DIR/../openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$ROOT_DIR/.openclaw}"
ENV_NAME="${ENV_NAME:-xagent}"

PROVIDER_ID="${PROVIDER_ID:-localov}"
BASE_URL="${BASE_URL:-http://127.0.0.1:18080/v1}"
MODEL_ID="${MODEL_ID:-qwen25-coder-3b-int8-ov}"
API_KEY="${API_KEY:-stub-key}"

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "[ERROR] openclaw repo not found: $OPENCLAW_DIR"
  exit 1
fi

mkdir -p "$OPENCLAW_WORKSPACE"

# 在隔离 workspace 中暴露项目技能目录，避免把 onboarding 生成文件写到项目根目录
if [[ ! -e "$OPENCLAW_WORKSPACE/skills" ]]; then
  ln -s "$ROOT_DIR/skills" "$OPENCLAW_WORKSPACE/skills"
fi

cd "$OPENCLAW_DIR"
conda run -n "$ENV_NAME" pnpm openclaw onboard \
  --non-interactive --accept-risk --mode local \
  --workspace "$OPENCLAW_WORKSPACE" \
  --auth-choice custom-api-key \
  --custom-provider-id "$PROVIDER_ID" \
  --custom-compatibility openai \
  --custom-base-url "$BASE_URL" \
  --custom-model-id "$MODEL_ID" \
  --custom-api-key "$API_KEY" \
  --skip-channels --skip-ui --skip-skills --skip-health

echo "[DONE] OpenClaw onboard completed."
echo "workspace: $OPENCLAW_WORKSPACE"
echo "provider:  $PROVIDER_ID"
echo "base_url:  $BASE_URL"
echo "model_id:  $MODEL_ID"

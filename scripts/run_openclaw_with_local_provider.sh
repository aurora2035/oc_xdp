#!/usr/bin/env bash
set -euo pipefail

# 一键准备并运行 OpenClaw + 本地 OpenVINO Provider + Agent bridge
#
# 可配参数（环境变量）：
# - ENV_NAME: conda 环境名，默认 xagent
# - OPENCLAW_DIR: openclaw 仓库目录，默认 ../openclaw
# - OPENCLAW_WORKSPACE: OpenClaw 工作区目录，默认 .openclaw
# - MODEL_ID: 本地模型目录或 HF model id
# - MODEL_NAME: provider 对外暴露的 model 名称
# - PROVIDER_ID: OpenClaw custom provider id，默认 localov
# - DO_ONBOARD: 1=启动前先执行 onboard（默认 1）
# - RUN_E2E_TEST: 1=先跑 e2e 脚本再退出（默认 0）
#
# 使用示例：
# ENV_NAME=xagent bash scripts/run_openclaw_with_local_provider.sh
# RUN_E2E_TEST=1 bash scripts/run_openclaw_with_local_provider.sh

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${ENV_NAME:-xagent}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT_DIR/../openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$ROOT_DIR/.openclaw}"

MODEL_ID="${MODEL_ID:-/home/xiaodong/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov}"
MODEL_NAME="${MODEL_NAME:-qwen25-coder-3b-int8-ov}"
PROVIDER_ID="${PROVIDER_ID:-localov}"

DO_ONBOARD="${DO_ONBOARD:-1}"
RUN_E2E_TEST="${RUN_E2E_TEST:-0}"

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda not found"
  exit 1
fi

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "[ERROR] openclaw repo not found: $OPENCLAW_DIR"
  echo "        You can set OPENCLAW_DIR to your actual path."
  exit 1
fi

if [[ "$DO_ONBOARD" == "1" ]]; then
  echo "[1/3] Onboarding OpenClaw custom provider..."
  ENV_NAME="$ENV_NAME" \
  OPENCLAW_DIR="$OPENCLAW_DIR" \
  OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
  PROVIDER_ID="$PROVIDER_ID" \
  BASE_URL="http://127.0.0.1:18080/v1" \
  MODEL_ID="$MODEL_NAME" \
  API_KEY="stub-key" \
  bash "$ROOT_DIR/scripts/onboard_openclaw_local_provider.sh"
else
  echo "[1/3] Skip onboarding (DO_ONBOARD=$DO_ONBOARD)"
fi

if [[ "$RUN_E2E_TEST" == "1" ]]; then
  echo "[2/3] Running one-shot e2e test..."
  ENV_NAME="$ENV_NAME" \
  MODEL_ID="$MODEL_ID" \
  MODEL_NAME="$MODEL_NAME" \
  bash "$ROOT_DIR/scripts/test_openclaw_e2e.sh"
  echo "[3/3] Done (test mode)."
  exit 0
fi

echo "[2/3] Starting runtime with local provider..."
USE_LOCAL_PROVIDER=1 \
ENABLE_MOCK_MODEL=0 \
LOCAL_PROVIDER_MODEL_ID="$MODEL_ID" \
LOCAL_PROVIDER_MODEL_NAME="$MODEL_NAME" \
OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" \
ENV_NAME="$ENV_NAME" \
bash "$ROOT_DIR/scripts/start_openclaw_runtime.sh"

#!/usr/bin/env bash
set -euo pipefail

# 新机器从零初始化脚本
# - 准备 conda 环境 xagent
# - 安装 OpenClaw 依赖
# - 把 OpenClaw workspace 绑定到 Agent
# - 配置 custom mock provider

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
OPENCLAW_DIR="${OPENCLAW_DIR:-$DEMO_DIR/openclaw}"
ENV_NAME="${ENV_NAME:-xagent}"

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda not found. Please install Miniforge/Conda first."
  exit 1
fi

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "[INFO] openclaw repo not found, cloning into: $OPENCLAW_DIR"
  git clone https://github.com/openclaw/openclaw.git "$OPENCLAW_DIR"
fi

echo "[1/5] Ensure conda env: $ENV_NAME"
if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda create -n "$ENV_NAME" -y python=3.10
fi

echo "[2/5] Install runtime dependencies into conda env"
conda install -n "$ENV_NAME" -c conda-forge -y nodejs=22 pnpm
conda run -n "$ENV_NAME" python -m pip install -U pip pytest pyyaml numpy

echo "[3/5] Install OpenClaw workspace dependencies"
cd "$OPENCLAW_DIR"
conda run -n "$ENV_NAME" pnpm install

echo "[4/5] Configure OpenClaw workspace + mock provider"
conda run -n "$ENV_NAME" pnpm openclaw onboard \
  --non-interactive --accept-risk --mode local \
  --workspace "$ROOT_DIR" \
  --auth-choice custom-api-key \
  --custom-provider-id customstub \
  --custom-compatibility openai \
  --custom-base-url http://127.0.0.1:18080/v1 \
  --custom-model-id stub-planner-nlu \
  --custom-api-key stub-key \
  --skip-channels --skip-ui --skip-skills --skip-health

echo "[5/5] Verify Agent tests"
cd "$ROOT_DIR"
conda run -n "$ENV_NAME" python -m pytest -q tests/test_agent.py

echo "[DONE] New-machine bootstrap finished."
echo "Next: cd $ROOT_DIR && bash scripts/start_openclaw_runtime.sh"

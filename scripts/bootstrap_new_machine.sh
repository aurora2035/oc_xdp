#!/usr/bin/env bash
set -euo pipefail

# 新机器从零初始化脚本
# - 准备 conda 环境 xagent（如已存在则删除重建）
# - 安装 3rd_party 下的 whl 包
# - 安装 OpenClaw 依赖
# - 把 OpenClaw workspace 绑定到 Agent（配置隔离在 .openclaw/ 子目录）
# - 配置 custom mock provider

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
OPENCLAW_DIR="${OPENCLAW_DIR:-$DEMO_DIR/openclaw}"
ENV_NAME="${ENV_NAME:-xagent}"
THIRD_PARTY_DIR="$ROOT_DIR/3rd_party"
OPENCLAW_WORKSPACE="$ROOT_DIR/.openclaw"  # 配置隔离目录

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda not found. Please install Miniforge/Conda first."
  exit 1
fi

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "[INFO] openclaw repo not found, cloning into: $OPENCLAW_DIR"
  git clone https://github.com/openclaw/openclaw.git "$OPENCLAW_DIR"
fi

# [0/6] 检查并删除已存在的环境
echo "[0/6] Check existing conda env: $ENV_NAME"
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "[WARN] Environment '$ENV_NAME' already exists, removing it first..."
  conda env remove -n "$ENV_NAME" -y
  echo "[INFO] Old environment '$ENV_NAME' removed successfully"
fi

# [1/6] 创建新环境
echo "[1/6] Create conda env: $ENV_NAME"
conda create -n "$ENV_NAME" -y python=3.10

# [2/6] 安装基础依赖
echo "[2/6] Install runtime dependencies into conda env"
conda install -n "$ENV_NAME" -c conda-forge -y nodejs=22 pnpm
conda run -n "$ENV_NAME" python -m pip install -U pip pytest pyyaml numpy

# [3/6] 安装 3rd_party 下的 whl 包
echo "[3/6] Install 3rd_party whl packages"
if [[ -d "$THIRD_PARTY_DIR" ]]; then
  whl_files=("$THIRD_PARTY_DIR"/*.whl)
  if [[ -f "${whl_files[0]}" ]]; then
    echo "[INFO] Found whl files in $THIRD_PARTY_DIR, installing..."
    for whl_file in "${whl_files[@]}"; do
      if [[ -f "$whl_file" ]]; then
        echo "[INFO] Installing: $(basename "$whl_file")"
        conda run -n "$ENV_NAME" python -m pip install "$whl_file"
      fi
    done
  else
    echo "[WARN] No .whl files found in $THIRD_PARTY_DIR, skipping..."
  fi
else
  echo "[WARN] 3rd_party directory not found at $THIRD_PARTY_DIR, skipping..."
fi

# [4/6] 安装 OpenClaw 工作区依赖
echo "[4/6] Install OpenClaw workspace dependencies"
cd "$OPENCLAW_DIR"
conda run -n "$ENV_NAME" pnpm install

# [5/6] 在子目录中配置 OpenClaw（隔离 soul.md 等配置文件）
echo "[5/6] Configure OpenClaw workspace + mock provider (isolated in .openclaw/)"
mkdir -p "$OPENCLAW_WORKSPACE"
conda run -n "$ENV_NAME" pnpm openclaw onboard \
  --non-interactive --accept-risk --mode local \
  --workspace "$OPENCLAW_WORKSPACE" \
  --auth-choice custom-api-key \
  --custom-provider-id customstub \
  --custom-compatibility openai \
  --custom-base-url http://127.0.0.1:18080/v1  \
  --custom-model-id stub-planner-nlu \
  --custom-api-key stub-key \
  --skip-channels --skip-ui --skip-skills --skip-health

echo "[INFO] Config files generated in: $OPENCLAW_WORKSPACE"

# [6/6] 验证测试
echo "[6/6] Verify Agent tests"
cd "$ROOT_DIR"
conda run -n "$ENV_NAME" python -m pytest -q tests/test_agent.py

echo "[DONE] New-machine bootstrap finished."
echo "Config location: $OPENCLAW_WORKSPACE"
echo "Next: cd $ROOT_DIR && bash scripts/start_openclaw_runtime.sh"
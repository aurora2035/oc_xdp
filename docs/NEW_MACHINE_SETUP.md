# 新机器部署手册（From Zero）

## 前置条件

- Linux/macOS
- 已安装 Conda/Miniforge
- 可访问 GitHub

## 步骤 A：准备目录与仓库

```bash
# 创建工作目录
mkdir -p ~/demo
cd ~/demo

# 克隆 OpenClaw（若没有）
git clone https://github.com/openclaw/openclaw.git

# 你的 Agent 项目目录应为：~/demo/Agent
```

## 步骤 B：准备统一环境 `ttt`

```bash
# 创建环境（已存在可跳过）
conda create -n ttt -y python=3.10

# 安装运行时依赖（Node + pnpm）
conda install -n ttt -c conda-forge -y nodejs=22 pnpm

# 安装 Python 依赖
conda run -n ttt python -m pip install -U pip pytest pyyaml numpy
```

## 步骤 C：安装 OpenClaw 依赖

```bash
cd ~/demo/openclaw
conda run -n ttt pnpm install
```

## 步骤 D：初始化 OpenClaw 并绑定 Agent 工作区

```bash
cd ~/demo/openclaw

# 非交互初始化（含风险确认）
conda run -n ttt pnpm openclaw onboard \
  --non-interactive --accept-risk --mode local \
  --workspace ~/demo/Agent \
  --auth-choice custom-api-key \
  --custom-provider-id customstub \
  --custom-compatibility openai \
  --custom-base-url http://127.0.0.1:18080/v1 \
  --custom-model-id stub-planner-nlu \
  --custom-api-key stub-key \
  --skip-channels --skip-ui --skip-skills --skip-health
```

## 步骤 E：一键启动栈

```bash
cd ~/demo/Agent
bash scripts/start_openclaw_runtime.sh
```

## 步骤 F：验证

```bash
# 1) Agent 测试
cd ~/demo/Agent
conda run -n ttt python -m pytest -q tests/test_agent.py

# 2) bridge + mock health
curl -s http://127.0.0.1:8099/health
curl -s http://127.0.0.1:18080/health

# 3) OpenClaw 是否识别 workspace skill
cd ~/demo/openclaw
conda run -n ttt pnpm openclaw skills list --json | grep xdp-agent-bridge

# 4) 音频模式链路（返回 text + audio_b64，并落盘 wav）
cd ~/demo/Agent && conda run -n ttt python skills/xdp-agent-bridge/scripts/call_xdp_agent.py --text "给我一句温和护肤建议" --response-mode audio | python -c "import sys,json,base64;d=json.load(sys.stdin);open('/tmp/agent_tts.wav','wb').write(base64.b64decode(d['audio_b64']));print('/tmp/agent_tts.wav')"
```

说明：若当前使用 mock/stub TTS 后端，`audio_b64` 可能不是可播放 wav；切换到真实 TTS 后端即可试听。

## 一键化脚本

你也可以直接在 `Agent` 目录执行：

```bash
bash scripts/bootstrap_new_machine.sh
```

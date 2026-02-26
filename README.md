# oc w/ xdp

该项目架构如下：

- Input Layer：text / audio
- OpenClaw Runtime：使用其运行时推理（NLU/Planner 由模型驱动）
- xDP Agent Core：ASR/RAG/Generation/Memory 的业务执行链

---

## 1. 整体架构设计

```text
┌────────────────────────────────────────────────────────┐
│ Input Layer                                            │
│  - text                                                 │
│  - audio(bytes)                                         │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ OpenClaw Runtime (Node/TS)                             │
│  - 模型推理层（当前可用 mock provider）                 │
│  - Skills 机制加载 workspace/skills                    │
│  - 根据 SKILL.md 触发本地脚本                           │
└───────────────────────┬────────────────────────────────┘
                        │ HTTP / JSON
                        ▼
┌────────────────────────────────────────────────────────┐
│ Agent Bridge (Python)                                  │
│  - openclaw_bridge_server.py                           │
│  - /v1/assist 接口，调用 OpenClawAgent                 │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ xDP Agent Core (Python)                                │
│  - ASRSkill -> NLUSkill -> Planner -> RAG -> Generation│
│  - Memory 持久化（JSON）                                │
└────────────────────────────────────────────────────────┘
```

---

## 2. 每个模块做什么（模块职责）

### 2.1 Agent Core
- `agent/core.py`
  - 统一编排入口，负责：输入预处理、调用技能链、更新记忆、输出结果。
  - 支持 `text` 与 `audio`（audio 先走 ASR）。

- `agent/planner.py`
  - 根据 NLU 输出生成执行计划（有序 skill list）。
  - 处理条件分支（如 `skin_analysis` 且无 CV 时加 `cv_missing` 标记）。

- `agent/memory.py`
  - 管理三类记忆：对话历史（最多 3 轮）、用户画像、商品浏览记录（最多 5 个）。
  - JSON 持久化。

- `agent/config.py`
  - 加载 `config/agent.yaml`。
  - 支持 YAML（有 `PyYAML`）或 JSON 兼容格式。

### 2.2 Skills
- `agent/skills/base.py`
  - Skill 抽象基类：`name / description / parameters / execute()`。
  - 参数校验、回调机制。

- `agent/skills/asr_skill.py`
  - 尝试调用 `xdp_api.asr`，失败时回退到本地解码 fallback。

- `agent/skills/nlu.py`
  - 支持真实模型推理：`transformers` 本地 Qwen 或 `openai_compatible` 服务。
  - 当模型不可用时自动回退到规则模式，保证主链路可用。
  - 输出 `{intent, entities, skill_chain, confidence}`。

- `agent/skills/rag_skill.py`
  - 优先走 xDP embedding，失败时走 fallback embedding。
  - 本地相似度检索（FAISS-like）。

- `agent/skills/generation_skill.py`
  - 生成导购话术（当前为模板桩），后续可替换为本地 <=1B 模型推理。

### 2.3 OpenClaw 融合层
- `openclaw_bridge_server.py`
  - 给 OpenClaw skill 提供 HTTP 入口：`POST /v1/assist`。
  - 请求体推荐使用 `audio` 字段传音频（base64 / data URL / byte-array）。
  - `audio_b64` 仍可用，但仅作为向后兼容字段。

- `skills/xdp-agent-bridge/SKILL.md`
  - OpenClaw workspace skill 说明文档，指导 runtime 何时调用本地脚本。

- `skills/xdp-agent-bridge/scripts/call_xdp_agent.py`
  - OpenClaw skill 实际执行脚本，调用 bridge 并输出 JSON。

### 2.4 模型桩（便于快速联调）
- `openai_mock_server.py`
  - OpenAI-compatible mock provider。
  - 支持 `/v1/models`、`/v1/chat/completions`、`/v1/responses`（含 stream）。

### 2.5 本地模型 Provider（可替换）
- `providers/openvino_openai_provider/server.py`
  - OpenAI-compatible 本地模型服务（OpenVINO 后端）。
  - 用于把本地模型接入 OpenClaw custom provider。
  - 支持 `/v1/models`、`/v1/chat/completions`、`/v1/responses`。

---

## 3. 新机器从零开始构建（推荐）

> 目标：在新机器上一次性把 `Agent + OpenClaw + mock` 跑起来。

### 3.1 手工步骤

```bash
# 1) 克隆项目（示例路径）
mkdir -p ~/demo
cd ~/demo
# 假设 Agent 项目已在此目录，OpenClaw 未安装
git clone https://github.com/openclaw/openclaw.git

# 2) 准备 conda 环境（你要求统一用 xagent）
conda create -n xagent -y python=3.10
conda install -n xagent -c conda-forge -y nodejs=22 pnpm
conda run -n xagent python -m pip install -U pip pytest pyyaml numpy

# 3) 安装 OpenClaw 源码依赖
cd ~/demo/openclaw
conda run -n xagent pnpm install

# 4) 绑定 OpenClaw 工作区到 Agent，并配置 custom mock provider
conda run -n xagent pnpm openclaw onboard \
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

### 3.2 一键脚本

见：`scripts/bootstrap_new_machine.sh`

```bash
cd ~/demo/Agent
bash scripts/bootstrap_new_machine.sh
```

---

## 4. 启动与验证（最短路径）

### 4.1 一键启动全部运行栈

```bash
cd /home/demo/Agent
bash scripts/start_openclaw_runtime.sh
```

该脚本会做：
- 启动 Agent bridge（8099）
- 启动 mock model（18080，可通过 `ENABLE_MOCK_MODEL=0` 关闭）
- 启动 OpenClaw gateway

若要启用本地 OpenVINO provider（替代 mock）：

```bash
cd /home/demo/Agent
USE_LOCAL_PROVIDER=1 \
LOCAL_PROVIDER_MODEL_ID=/home/xiaodong/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov \
LOCAL_PROVIDER_MODEL_NAME=qwen25-coder-3b-int8-ov \
bash scripts/start_openclaw_runtime.sh
```

### 4.2 自检命令

```bash
# 1) health 检查
curl -s http://127.0.0.1:8099/health
curl -s http://127.0.0.1:18080/health

# 2) 验证 OpenClaw 已识别 skill
cd /home/demo/openclaw
conda run -n xagent pnpm openclaw skills list --json | grep xdp-agent-bridge

# 3) 直接验证 skill 调 bridge
cd /home/xAgent
conda run -n xagent python skills/xdp-agent-bridge/scripts/call_xdp_agent.py --text "我长痘了，推荐个精华"

# 4) 直接验证 bridge 的 audio 入参（推荐字段：audio）
python - <<'PY'
import base64, json
from pathlib import Path
import requests

audio_path = Path('/home/api_test/en_wav/hap.wav')
payload = {
  "text": "",
  "response_mode": "text",
  "audio": base64.b64encode(audio_path.read_bytes()).decode("utf-8"),
}
resp = requests.post("http://127.0.0.1:8099/v1/assist", json=payload, timeout=120)
print(resp.status_code)
print(json.dumps(resp.json(), ensure_ascii=False, indent=2)[:800])
PY
```

### 4.3 OpenClaw skill 音频模式快速验证

当你需要验证 TTS 音频链路（bridge 返回 `audio_b64`）时，执行：

```bash
cd /home/demo/Agent
conda run -n xagent python skills/xdp-agent-bridge/scripts/call_xdp_agent.py \
  --text "给我一句温和护肤建议" \
  --response-mode audio
```

预期：返回 JSON 同时包含 `text` 与 `audio_b64` 字段。

可选：把 `audio_b64` 直接落盘为 wav，便于试听链路。

单行版（直接生成 `/tmp/agent_tts.wav`）：

```bash
cd /home/demo/Agent && conda run -n xagent python skills/xdp-agent-bridge/scripts/call_xdp_agent.py --text "给我一句温和护肤建议" --response-mode audio | python -c "import sys,json,base64;d=json.load(sys.stdin);open('/tmp/agent_tts.wav','wb').write(base64.b64decode(d['audio_b64']));print('/tmp/agent_tts.wav')"
```

```bash
cd /home/demo/Agent
conda run -n xagent python skills/xdp-agent-bridge/scripts/call_xdp_agent.py \
  --text "给我一句温和护肤建议" \
  --response-mode audio > /tmp/agent_tts.json

python -c "import json,base64;d=json.load(open('/tmp/agent_tts.json','r',encoding='utf-8'));open('/tmp/agent_tts.wav','wb').write(base64.b64decode(d['audio_b64']));print('/tmp/agent_tts.wav')"
```

说明：如果你当前使用的是 mock/stub TTS 后端，`audio_b64` 可能不是可播放 wav 数据；切到真实 TTS 后端即可正常试听。

---

## 5. 开发与测试

```bash
cd /home/demo/Agent
conda run -n xagent python -m pytest -q tests/test_agent.py
```

---

## 6. 代码注释规范（本项目）

本项目已经在关键模块补齐了：
- 模块级 docstring：模块职责、输入输出说明。
- 关键类/函数 docstring：参数含义、行为、fallback 逻辑。
- 启动脚本注释：每一步做什么、为什么。

如果你后续要接入真实模型，当前建议优先推进：
1. `agent/skills/generation_skill.py`（模板桩 -> 模型生成）

### NLU 模型配置示例

`config/agent.yaml` 中 `nlu` 段支持两种模式：

1) 本地 Qwen（transformers）

```json
"nlu": {
  "backend": "transformers",
  "model": "Qwen/Qwen2.5-0.5B-Instruct",
  "optimization": "ipex_llm_int8_amx",
  "temperature": 0.0,
  "max_new_tokens": 256
}
```

2) OpenAI 兼容接口（例如本地 vLLM/TGI 网关）

```json
"nlu": {
  "backend": "openai_compatible",
  "model": "Qwen2.5-0.5B-Instruct",
  "openai_base_url": "http://127.0.0.1:18080/v1",
  "openai_model": "Qwen2.5-0.5B-Instruct",
  "openai_api_key": "stub-key",
  "temperature": 0.0,
  "max_new_tokens": 256
}
```

### NLU 快速验证

```bash
cd /home/demo/Agent
conda run -n xagent python main.py --text "我长痘了，推荐个精华"
```

预期：输出中的 `nlu.model.backend` 为 `transformers` 或 `openai_compatible`，且 `fallback=false`。

### OpenClaw-first 编排模式（推荐）

当前支持把 NLU/Planner 主逻辑交给 OpenClaw，上游结果优先：

```json
"orchestration": {
  "use_upstream_planner": true,
  "strict_upstream_plan": true
}
```

- `use_upstream_planner=true`：本地 Agent 不再主动运行本地 NLU/Planner，优先执行上游传入的 `nlu/plan`。
- `strict_upstream_plan=true`：强制要求上游必须传 `plan`，否则报错。
- `strict_upstream_plan=true`：默认模式，强制要求上游必须传 `plan`，否则直接报错（严格 OpenClaw-only）。

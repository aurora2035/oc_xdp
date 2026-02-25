# 架构说明（Architecture）

## 目标

在 OpenClaw runtime 内复用其推理调度能力（模型驱动 NLU/Planner），同时把业务执行沉淀在 Python `Agent` 项目中，便于后续替换为真实 xDP 能力。

## 分层

1. **OpenClaw Runtime 层**
   - 负责会话、模型调用、skills 发现与执行。
   - 从 `Agent/skills/xdp-agent-bridge/SKILL.md` 读取 skill 指令。

2. **Bridge 层（HTTP）**
   - `openclaw_bridge_server.py`
   - 向上：接收 OpenClaw skill 脚本请求。
   - 向下：调用 `OpenClawAgent`。

3. **Agent Core 层**
   - `agent/core.py`：统一编排。
   - `agent/planner.py`：技能链计划。
   - `agent/memory.py`：状态持久化。
   - `agent/skills/*`：可替换的技能单元。

4. **Model Stub 层（开发态）**
   - `openai_mock_server.py`
   - 用于替代真实云模型，保障本地闭环。

## 数据流

- 文本：`OpenClaw -> skill script -> bridge -> nlu/planner/rag/generation -> bridge -> OpenClaw`
- 音频：`OpenClaw/调用方 -> bridge(audio_b64) -> asr -> nlu/planner/...`

## 关键约束映射

- CV skill 未实现：`planner` 对 `cv_result is None` 做了显式分支。
- <=1B 模型约束：NLU/Generation 使用桩化 profile（Qwen2.5-0.5B 标记）。
- fallback：ASR/RAG/Generation 均具备失败回退。
- 持久化：`data/agent_memory.json`。

## 后续替换点

- `agent/skills/nlu.py`：规则桩 -> 真模型推理。
- `agent/skills/generation_skill.py`：模板桩 -> 真生成模型。
- `agent/skills/rag_skill.py`：本地 catalog -> 真向量库/商品库。

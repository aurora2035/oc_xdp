## **整体架构**

用户交互层 支持文字/ 语音两种输入方式

网关路由层 OpenClaw (Node.js) - 意图识别& 技能路由

业务逻辑层 xDP Agent Core (Python) - 导购核心逻辑

能力支撑层 ASR / NLU / RAG / Generation / TTS

<br />

## **进展与规划**

| 阶段      | 目标                                                    | 状态   |
| :------ | :---------------------------------------------------- | :--- |
| Phase 1 | 搭建基础架构，支持文本交互                                         | Done |
| Phase 2 | 接入xDP API语音能力（ASR/TTS）                                | WIP  |
| Phase 3 | OpenClaw 上游主导 NLU/Planner，bridge 透传执行                  | 基本完成（稳定性收口中） |
| Phase 4 | 接入商品库(demo)， end-to-end联调, 保证性能(若不满足性能将NLU LLM迁移到GPU) | Wait |

<br />

### **当前真实状态（2026-02-26）**

| Skill      | 职责         | 状态                    |
| :--------- | :--------- | :-------------------- |
| ASR        | 语音→ 文字     | 已接入 xDP API；`num_runs<=0` 自动矫正为 `1` |
| NLU        | 意图识别+实体提取 | 已改为 OpenClaw 上游主导（本地不兜底） |
| Planner    | 计划编排       | 已改为 OpenClaw 上游主导；支持 strict upstream plan |
| RAG        | 商品向量检索     | 本地检索链路可执行（mock 数据） |
| Generation | 对话生成       | 模板生成可执行（后续可替换模型） |
| TTS        | 文字→语音      | xDP 已接入，但未纳入本轮验收（暂不阻塞） |
| Memory     | 对话历史&用户画像 | JSON 持久化已稳定工作 |

<br />

### **已完成验证**

- `scripts/test_openclaw_e2e.sh` 通过（provider 接口 + bridge 严格上游链路）。
- `tests/test_agent.py` 中严格模式单测通过：
  - `strict_upstream_mode_requires_plan`
  - `strict_upstream_mode_executes_plan`
- 结论：**NLU/Planner 主链路已通**（OpenClaw 上游下发 `nlu/plan` → bridge 透传 → 本地执行）。

### **当前仍缺（先不含 TTS）**

1. **Gateway 真实对话回路稳定性收口**
	- 需证明：OpenClaw gateway -> `xdp-agent-bridge` skill -> Python bridge -> agent core 全链路可用。
   - 当前症状：agent 回合偶发 `Request was aborted`/`Connection error`，属于网关回路稳定性问题，不是 NLU/Planner 功能缺失。
2. **OpenClaw workspace 与 skill 可见性一致性**
	- `OPENCLAW_WORKSPACE` 必须指向包含 `skills/xdp-agent-bridge` 的目录。
3. **Gateway 模型上下文窗口阈值校准**
	- 若 provider 模型元数据上下文窗口过小（如 4096），`openclaw agent` 会拒绝执行，需要校准到 >=16000。

### **一键脚本（新增）**

- `scripts/test_openclaw_gateway_e2e.sh`
  - 覆盖：onboard local provider、启动 provider+bridge+gateway、检查 skill 可见、触发 gateway agent turn、校验 bridge memory 落盘。

### **建议执行顺序**

```bash
# 1) 跑 gateway 真实回路（不含 TTS）
ENV_NAME=xagent bash scripts/test_openclaw_gateway_e2e.sh

# 2) 若仅做 provider+bridge 快速回归
ENV_NAME=xagent bash scripts/test_openclaw_e2e.sh
```

---

### **NLU 模型选型备注（for Xeon）**

<br />

| Option                  | Configuration                 | Approach                                                                                | Best For              |
| :---------------------- | :---------------------------- | :-------------------------------------------------------------------------------------- | :-------------------- |
| **A. Lightweight**      | TextCNN/BERT-Tiny + Qwen 0.5B | Hybrid architecture:Traditional classifier for intent detection, small LLM for planning | Cost-sensitive pilots |
| **B. Balanced**         | Qwen2.5-1.5B-Instruct         | Unified single model                                                                    | Production deployment |
| **C. High-Performance** | Qwen2.5-3B-Instruct (INT4)    | Quantized large model                                                                   | Complex conversations |

### **DEMO用例**

场景：用户语音询问” 我长痘了，推荐个精华”

<br />

```
用户语音输入
1. [ASR Skill] 语音识别→ "我长痘了，推荐个精华"
2. [NLU Skill] 意图识别→ product_qa（商品咨询） 实体提取→ concern: 痘痘, product_type: 精华
3. [RAG Skill] 向量检索→ 返回「净痘修护精华」等候选商品
4. [Generation] 话术生成→ "宝子你这个问题问得太对了！ 可以优先看「净痘修护精华」..."
5. [Memory] 持久化→ 记录对话历史& 用户关注点
```


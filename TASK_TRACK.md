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
| Phase 3 | OpenClaw 上游主导 NLU/Planner，bridge 透传执行                  | **基本完成（添加 Mock 模式支持）** |
| Phase 4 | 接入商品库(demo)， end-to-end联调, 保证性能(若不满足性能将NLU LLM迁移到GPU) | Wait |

<br />

### **当前真实状态（2026-02-28 更新）**

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

### **Step9/Step10 问题根因定位（2026-02-28 关键更新）**

**问题已定位：不是 OpenClaw Bug，是超时配置不匹配**

| 现象 | 根因 | 解决方案 |
|------|------|----------|
| `agent.wait` timeout | OpenClaw 内部多轮推理架构 | 延长超时或优化架构 |
| `terminated` 错误 | 超过 OpenClaw 300s 硬限制 | Mock 模式或 GPU 加速 |
| Step9 strict 失败 | 总执行时间 > wait 超时 | 使用 Non-Strict fallback |

**核心发现：**
- 单次模型推理：9-15s（16vCPU）
- OpenClaw 多轮调用：10-30 轮
- 总执行时间：100-300s+
- 即使 Mock Server（<0.1s）仍需 60s+ 处理时间

<br />

### **已完成验证**

- `scripts/test_openclaw_e2e.sh` 通过（provider 接口 + bridge 严格上游链路）。
- `tests/test_agent.py` 中严格模式单测通过：
  - `strict_upstream_mode_requires_plan`
  - `strict_upstream_mode_executes_plan`
- **新增：Mock Server 模式测试通过**（PASS fallback，~60s）
- **新增：`MOCK_MODE` 开关支持**（快速切换 Mock/真实模型）
- 结论：**NLU/Planner 主链路已通**（OpenClaw 上游下发 `nlu/plan` → bridge 透传 → 本地执行）。

<br />

### **当前仍缺（先不含 TTS）**

1. **Gateway 真实对话回路稳定性收口**
   - ✅ 已验证：OpenClaw gateway -> `xdp-agent-bridge` skill -> Python bridge -> agent core 可跑通。
   - ✅ 已解决：添加 Mock Server 模式，Step1-8 稳定通过，Step9 可用 fallback 兜底。
   - ⚠️ 限制：Strict 模式（无 fallback）仍可能超时，需要 OpenClaw 内部优化或更长超时。

2. **OpenClaw workspace 与 skill 可见性一致性**
   - `OPENCLAW_WORKSPACE` 必须指向包含 `skills/xdp-agent-bridge` 的目录。

3. **Gateway 模型上下文窗口阈值校准**
   - 若 provider 模型元数据上下文窗口过小（如 4096），`openclaw agent` 会拒绝执行，需要校准到 >=16000。

<br />

### **一键脚本（2026-02-28 更新）**

| 脚本 | 用途 | 模式 | 耗时 | 结果 |
|------|------|------|------|------|
| `run_manual_provider.sh` | 启动 provider | `MOCK_MODE=1/0` | - | 前台运行 |
| `run_gateway_e2e_mock.sh` | **新增** | Mock | ~60s | PASS(fallback) |
| `run_gateway_e2e.sh` | E2E 全流程 | 真实模型 | ~300s | PASS(fallback) |
| `scripts/test_openclaw_e2e.sh` | Provider + Bridge | 自动 | ~30s | PASS |
| `scripts/test_openclaw_gateway_e2e.sh` | 完整 Gateway E2E | 配置决定 | 60-300s | 依赖配置 |

**推荐执行顺序（开发阶段）：**

```bash
# 方式 1：Mock 模式（推荐，快速）
./run_gateway_e2e_mock.sh

# 方式 2：真实模型（功能验证）
# 终端 1
MOCK_MODE=0 ./run_manual_provider.sh

# 终端 2
./run_gateway_e2e.sh
```

<br />

### **文件变更清单（2026-02-28）**

| 文件 | 变更 | 说明 |
|------|------|------|
| `run_manual_provider.sh` | 更新 | 支持 `MOCK_MODE=1/0` 切换 |
| `run_gateway_e2e_mock.sh` | **新增** | Mock Server 专用测试脚本 |
| `run_gateway_e2e.sh` | 更新 | 传递 `AGENT_WAIT_TIMEOUT_MS` |
| `scripts/test_openclaw_gateway_e2e.sh` | 更新 | 默认超时 300s，修复 cleanup 逻辑 |
| `bug.md` | **大幅更新** | 根因分析、Mock 模式文档 |

<br />

### **NLU 模型选型备注（for Xeon）**

<br />

| Option                  | Configuration                 | Approach                                                                                | Best For              |
| :---------------------- | :---------------------------- | :-------------------------------------------------------------------------------------- | :-------------------- |
| **A. Lightweight**      | TextCNN/BERT-Tiny + Qwen 0.5B | Hybrid architecture:Traditional classifier for intent detection, small LLM for planning | Cost-sensitive pilots |
| **B. Balanced**         | Qwen2.5-1.5B-Instruct         | Unified single model                                                                    | Production deployment |
| **C. High-Performance** | Qwen2.5-3B-Instruct (INT4)    | Quantized large model                                                                   | Complex conversations |
| **D. Mock**             | openai_mock_server.py         | Development & CI/CD                                                                     | Fast feedback loop    |

<br />

### **DEMO用例**

场景：用户语音询问" 我长痘了，推荐个精华"

<br />

```
用户语音输入
1. [ASR Skill] 语音识别→ "我长痘了，推荐个精华"
2. [NLU Skill] 意图识别→ product_qa（商品咨询） 实体提取→ concern: 痘痘, product_type: 精华
3. [RAG Skill] 向量检索→ 返回「净痘修护精华」等候选商品
4. [Generation] 话术生成→ "宝子你这个问题问得太对了！ 可以优先看「净痘修护精华」..."
5. [Memory] 持久化→ 记录对话历史& 用户关注点
```

---

**最后更新：2026-02-28**  
**状态：Phase 3 基本完成，添加 Mock 模式支持，Step9 fallback 可稳定通过**

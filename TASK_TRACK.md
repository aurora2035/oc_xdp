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
| Phase 3 | OpenClaw 上游主导 NLU/Planner，bridge 透传执行                  | **架构调整中（重要发现）** |
| Phase 4 | 接入商品库(demo)， end-to-end联调, 保证性能(若不满足性能将NLU LLM迁移到GPU) | Wait |

<br />

### **当前真实状态（2026-02-28 更新）**

| Skill      | 职责         | 状态                    |
| :--------- | :--------- | :-------------------- |
| ASR        | 语音→ 文字     | 已接入 xDP API；`num_runs<=0` 自动矫正为 `1` |
| NLU        | 意图识别+实体提取 | **架构调整：OpenClaw 不支持模块化 NLU，需直接调用模型** |
| Planner    | 计划编排       | **架构调整：同上** |
| RAG        | 商品向量检索     | 本地检索链路可执行（mock 数据） |
| Generation | 对话生成       | 模板生成可执行（后续可替换模型） |
| TTS        | 文字→语音      | xDP 已接入，但未纳入本轮验收（暂不阻塞） |
| Memory     | 对话历史&用户画像 | JSON 持久化已稳定工作 |

<br />

### **Phase 3 架构调整说明（2026-02-28 重要更新）**

#### 关键发现

**OpenClaw 不支持只使用 NLU/Planner 模块**

经过源码分析确认：
- ❌ OpenClaw 是**完整对话 Agent** 框架
- ❌ **没有** `plan-only` 或 `nlu-only` 模式
- ❌ **不支持**只返回 plan 而不执行完整循环
- ✅ OpenClaw 设计目标是**端到端对话助手**

#### 架构不匹配分析

| 维度 | 用户期望 | OpenClaw 实际 | 结果 |
|------|----------|---------------|------|
| **定位** | NLU/Planner 工具库 | 完整对话 Agent | ❌ 不匹配 |
| **调用方式** | 函数式（输入→输出） | 对话式（多轮循环） | ❌ 不匹配 |
| **输出** | Plan JSON | 对话回复文本 | ❌ 不匹配 |
| **执行流程** | 1-2 轮 | 3-5 轮完整循环 | ❌ 超时 |

#### 调整方案

**原方案（不可行）：**
```
用户 → OpenClaw (NLU/Planner) → Plan → xDP Agent (执行)
```

**新方案（推荐）：**
```
用户 → 直接调用模型 (NLU/Planner) → Plan → xDP Agent (执行)
       ↑
   绕过 OpenClaw Agent 循环
```

**方案对比：**

| 方案 | 实现难度 | 执行时间 | 可行性 |
|------|----------|----------|--------|
| A. 直接调用模型 | 低 | < 15s | ✅ 推荐 |
| B. 继续使用 OpenClaw | 低 | 300s+ | ⚠️ 超时 |
| C. 换用 LangChain | 中 | < 5s | ✅ 备选 |
| D. 修改 OpenClaw | 高 | < 15s | ❌ 不推荐 |

<br />

### **已完成验证**

- `scripts/test_openclaw_e2e.sh` 通过（provider 接口 + bridge 严格上游链路）。
- `tests/test_agent.py` 中严格模式单测通过：
  - `strict_upstream_mode_requires_plan`
  - `strict_upstream_mode_executes_plan`
- **新增：Mock Server 模式测试通过**（PASS fallback，~60s）
- **新增：`MOCK_MODE` 开关支持**（快速切换 Mock/真实模型）
- **新增：架构分析确认 OpenClaw 不支持模块化 NLU/Planner**
- 结论：**NLU/Planner 需改用直接调用模型方案**。

<br />

### **当前仍缺（先不含 TTS）**

1. **Phase 3 架构调整**
   - ✅ 已发现：OpenClaw 不支持模块化 NLU/Planner
   - ⏳ 待实现：直接调用模型做 NLU/Planner（方案 A）
   - ⏳ 待评估：LangChain 替代方案（方案 C）

2. **Gateway 真实对话回路稳定性**
   - ✅ 已验证：OpenClaw gateway → `xdp-agent-bridge` skill → Python bridge → agent core 可跑通。
   - ✅ 已解决：添加 Mock Server 模式，Step1-8 稳定通过，Step9 可用 fallback 兜底。
   - ⚠️ 限制：OpenClaw 完整 Agent 循环导致超时，需架构调整。

3. **OpenClaw workspace 与 skill 可见性一致性**
   - `OPENCLAW_WORKSPACE` 必须指向包含 `skills/xdp-agent-bridge` 的目录。

4. **Gateway 模型上下文窗口阈值校准**
   - 若 provider 模型元数据上下文窗口过小（如 4096），`openclaw agent` 会拒绝执行，需要校准到 >=16000。

<br />

### **一键脚本（2026-02-28 更新）**

| 脚本 | 用途 | 模式 | 耗时 | 结果 | 备注 |
|------|------|------|------|------|------|
| `run_manual_provider.sh` | 启动 provider | `MOCK_MODE=1/0` | - | 前台运行 | 支持 Mock/真实模型 |
| `run_gateway_e2e_mock.sh` | **新增** | Mock | ~60s | PASS(fallback) | **推荐开发使用** |
| `run_gateway_e2e.sh` | E2E 全流程 | 真实模型 | ~300s | PASS(fallback) | 功能验证 |
| `scripts/test_openclaw_e2e.sh` | Provider + Bridge | 自动 | ~30s | PASS | 快速回归 |
| `scripts/test_openclaw_gateway_e2e.sh` | 完整 Gateway E2E | 配置决定 | 60-300s | 依赖配置 | 完整流程 |

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
| `bug.md` | **大幅更新** | 架构分析、OpenClaw 限制说明 |
| `TASK_TRACK.md` | **更新** | Phase 3 架构调整说明 |

<br />

### **后续行动计划**

#### 立即执行（本周）
- [ ] 实现方案 A：直接调用模型做 NLU/Planner
- [ ] 绕过 OpenClaw Agent 循环
- [ ] 集成到 xDP Agent Core

#### 短期（下周）
- [ ] 测试直接调用模型的准确性和稳定性
- [ ] 对比 OpenClaw 和直接调用的效果
- [ ] 确定最终架构方案

#### 中期（本月）
- [ ] 如果场景复杂，评估 LangChain 替代方案
- [ ] 完整测试端到端链路
- [ ] 性能优化（如需要）

<br />

### **NLU 模型选型备注（for Xeon）**

<br />

| Option                  | Configuration                 | Approach                                                                                | Best For              |
| :---------------------- | :---------------------------- | :-------------------------------------------------------------------------------------- | :-------------------- |
| **A. Lightweight**      | TextCNN/BERT-Tiny + Qwen 0.5B | Hybrid architecture:Traditional classifier for intent detection, small LLM for planning | Cost-sensitive pilots |
| **B. Balanced**         | Qwen2.5-1.5B-Instruct         | Unified single model                                                                    | Production deployment |
| **C. High-Performance** | Qwen2.5-3B-Instruct (INT4)    | Quantized large model                                                                   | Complex conversations |
| **D. Direct Call**      | Qwen2-0.5B (OpenVINO)         | **绕过 OpenClaw，直接调用模型做 NLU/Planner**                                            | **Current workaround** |

<br />

### **DEMO用例**

场景：用户语音询问" 我长痘了，推荐个精华"

<br />

```
用户语音输入
1. [ASR Skill] 语音识别→ "我长痘了，推荐个精华"
2. [NLU/Planner] 直接调用模型（新方案）
   - 意图识别→ product_qa（商品咨询）
   - 实体提取→ concern: 痘痘, product_type: 精华
   - 计划生成→ ["rag", "generation"]
3. [RAG Skill] 向量检索→ 返回「净痘修护精华」等候选商品
4. [Generation] 话术生成→ "宝子你这个问题问得太对了！ 可以优先看「净痘修护精华」..."
5. [Memory] 持久化→ 记录对话历史& 用户关注点
```

---

**最后更新：2026-02-28**  
**状态：Phase 3 架构调整中，OpenClaw 不支持模块化 NLU/Planner，改用直接调用模型方案**  
**下一步：实现直接调用模型做 NLU/Planner**

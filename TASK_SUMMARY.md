**项目状态**：架构调整中，需决策技术路线

---

## 1. 执行摘要

**核心结论**：项目当前遭遇**架构层不匹配**问题。上游框架 OpenClaw 是完整对话 Agent，不支持作为 NLU/Planner 模块被调用，导致 Step 9 性能瓶颈（300s 超时 vs 预期 22s）。

**当前进展**：基础链路已跑通（Step 1-8 稳定，Step 10 通过），但 Step 9 需架构调整才能稳定达标。

**决策需求**：需在"临时止血方案"与"架构重构方案"间做出技术路线选择。

---

## 2. 项目背景与目标

### 2.1 目标架构（README 规划）
构建"OpenClaw 负责意图识别与规划，xDP Agent 负责业务执行"的分层架构：
- **网关层**：OpenClaw 提供 NLU + Planner 能力
- **执行层**：xDP Agent 负责 RAG、话术生成、记忆管理

### 2.2 当前阶段
- **Phase 1**（基础架构）：✅ 已完成
- **Phase 2**（ASR/TTS 接入）：🔄 进行中
- **Phase 3**（NLU/Planner 集成）：⚠️ **架构调整中（关键阻塞）**

---

## 3. 当前进展（已完成工作）

### 3.1 端到端测试流程说明（Step 1-10）

当前采用 `test_openclaw_gateway_e2e.sh` 脚本进行完整的十步验证，覆盖从环境准备到业务闭环的全链路：

| 步骤 | 环节名称 | 具体工作内容 | 当前状态 |
|------|----------|--------------|----------|
| **Step 1** | 环境清理 | 停止残留进程（Bridge、Provider、Gateway），释放端口 8099/18080/18789，确保测试环境干净 | ✅ 稳定 |
| **Step 2** | OpenClaw 初始化 | 执行 `onboard`，配置 custom provider（连接本地 OpenVINO 模型或 Mock），绑定 workspace | ✅ 稳定 |
| **Step 3** | 配置修正 | 自动 Patch OpenClaw 配置文件：设置模型上下文窗口 ≥32000、max_tokens=384、Agent timeout=600s，避免默认配置拒绝执行 | ✅ 稳定 |
| **Step 4** | 运行时启动 | 启动三大组件：Agent Bridge（8099）、Model Provider（18080）、OpenClaw Gateway（18789），支持手动/自动 Provider 模式 | ✅ 稳定 |
| **Step 5** | 健康检查 | 轮询验证：Provider /health、Bridge /health、Gateway health，确保全链路就绪 | ✅ 稳定 |
| **Step 6** | Provider 冒烟测试 | 直接调用模型接口（发送"请回复：ok"），验证模型推理层可用，排除模型加载失败问题 | ✅ 稳定 |
| **Step 7** | Bridge 直连测试 | **关键预检**：绕过 OpenClaw，直接 POST 到 Bridge（`8099/v1/assist`），携带预置 Plan 和 NLU 结果，验证 xDP Agent Core 执行链路（RAG→Generation→Memory）**不依赖 OpenClaw 也能工作** | ✅ 稳定 |
| **Step 8** | Skill 可见性检查 | 验证 OpenClaw Gateway 能识别到 `xdp-agent-bridge` skill（`openclaw skills list`），确保 Gateway 层配置正确 | ✅ 稳定 |
| **Step 9** | **Gateway Agent 调用** | **核心难点**：通过 `openclaw gateway call agent` 发送用户请求（"我长痘了，推荐个精华"），触发 OpenClaw 完整 Agent 循环，等待其决策调用 xDP skill。包含 `agent.call`（发送）和 `agent.wait`（等待完成，最长 300s×2 次）两个子阶段 | ⚠️ **Timeout/不稳定** |
| **Step 10** | **Memory 持久化验证** | 验证对话历史是否成功写入 `data/agent_memory.json`，确认业务数据落盘，形成完整闭环 | ✅ 验证通过 |

### 3.2 功能验证完成情况

**已稳定步骤（Step 1-8 & Step 10）：**
- ✅ **Mock Server 模式**：新增 `MOCK_MODE` 开关，模型响应从 9s 降至 &lt;0.1s，测试提速 5-10 倍，Step 1-8 全部 60s 内通过
- ✅ **基础链路连通**：Step 7（Bridge 直连）验证通过，证明 **xDP Agent Core 独立执行能力完好**（NLU/Planner 可本地运行，不依赖 OpenClaw）
- ✅ **Memory 系统**：Step 10 验证通过，对话历史 JSON 持久化稳定工作
- ✅ **一键脚本体系**：4 个脚本覆盖 Mock/真实模型场景（`run_gateway_e2e_mock.sh` ~60s，`run_gateway_e2e.sh` ~300s）

**待解决阻塞（Step 9）：**
- ⚠️ **Strict 模式不稳定**：Step 9 在 `STRICT_GATEWAY_WAIT=1`（严格要求 OpenClaw 完成 Agent 循环）下，因 OpenClaw 内部多轮推理（3-5 轮，每轮 9s+，上下文 2.7 万字符）导致 300s 超时
- ⚠️ **当前 Fallback 兜底**：通过 `strict_upstream_plan=false` + Bridge 超时 120s 配置，Step 9 可 `PASS(fallback)`，即 OpenClaw 超时后自动降级为直接调用 Bridge（同 Step 7 逻辑），但这**违背了"OpenClaw 负责规划"的架构初衷**

### 3.3 关键代码
- `nlu_planner_direct.py`：**已完成开发**，支持直接调用模型做 NLU+Planner（单次调用 &lt;15s），**尚未接入主流程**
- Agent Bridge：HTTP 接口稳定，支持 text/audio 双模输入
- E2E 测试脚本：覆盖 Provider、Bridge、Gateway 三层

---

## 4. 核心挑战

### 4.1 挑战一：OpenClaw 架构定位不匹配（根本问题）

**现象**：Step 9 持续超时（300s+），`agent.wait` 无法完成。

**根因定位**：
- **预期**：OpenClaw 作为"NLU/Planner 工具库"，函数式调用（输入→输出 Plan JSON），耗时预期 22s（12s NLU + 10s Planner）
- **实际**：OpenClaw 是**完整对话 Agent**，必须执行"理解→计划→执行→生成最终回复"的 3-5 轮循环，每轮处理 2.7 万字符上下文，总耗时 300s+

**分析**：
- 源码分析确认：OpenClaw 无 `plan-only` 模式，无 `nlu-only` 接口，必须生成最终用户回复（`role: "assistant"`）
- Session 文件显示：`content=[]`，OpenClaw 在生成最终回复时 timeout，而非返回 Plan

### 4.2 挑战二：Strict 模式与行为冲突

**现象**：开启 `strict_upstream_plan=true` 时链路直接报错。

**根因**：
- 配置要求上游必须传入 `plan` 参数
- 但 OpenClaw 调用 xDP skill 时**不传 plan**（因其设计是自身生成回复，非传计划给下游执行）
- 结果：strict 校验直接拒绝，触发 `strict_upstream_mode_requires_plan` 错误

### 4.3 挑战三：超时配置硬编码

**当前阻塞点**：
- `call_xdp_agent.py:63`：HTTP 超时硬编码 10s，真实模型场景下频繁超时
- `agent.yaml`：缺乏灵活的环境变量配置机制

---

## 5. 解决方案与实施路线

提供三级方案，按优先级递进：

### 5.1 P1：临时绕过（不改动架构）

**目标**：保障现有链路可跑通，消除硬性阻塞。

**措施**：
1. **关闭 Strict 模式**：`strict_upstream_plan: false`，允许 fallback 本地生成计划
2. **超时配置化**：Bridge 超时调整为 60-120s（环境变量可配），Step 9 等待超时调整为 300s
3. **保持 Mock 兜底**：开发阶段使用 Mock 模式（60s 内完成）

**风险**：OpenClaw 实际成为"摆设"，xDP 本地 fallback 逻辑承担全部工作，未解决架构不匹配问题。

### 5.2 P2：架构重构（推荐方案，2周内落地）

**目标**：实现 README 原设想的"OpenClaw 轻量网关 + xDP 核心大脑"架构。

**核心策略**：**绕过 OpenClaw Agent 逻辑，启用 Direct NLU/Planner**

**具体实施**：
1. **复用已有代码**：接入已开发的 `nlu_planner_direct.py`，单次模型调用（&lt;15s）替代 OpenClaw 多轮循环
2. **职责重新划分**：
   - **OpenClaw**：退化为 API 网关，仅做请求路由与会话管理，不做推理
   - **xDP Agent**：承担 NLU + Planner + 执行全链路（本地直接调用模型生成 Plan，本地执行 RAG/Generation）
3. **模式切换**：通过 `USE_DIRECT_NLU_PLANNER=true` 环境变量切换，保留原链路做 fallback

**预期收益**：
- Step 9 耗时从 300s 降至 &lt;15s
- 稳定通过 Strict 模式，不再依赖 fallback
- 架构符合原设计意图（OpenClaw 做网关，xDP 做执行）

### 5.3 P3：长期优化

**目标**：评估是否完全替换 OpenClaw 或引入 LangChain/AutoGen 等框架。

**考虑因素**：
- 若 OpenClaw 生态价值有限，可考虑完全移除，xDP 直接对外提供 HTTP 接口
- 若需复杂多 Agent 协作，评估 LangChain 等模块化框架


**不推荐继续尝试修改 OpenClaw 源码**（方案 3）：
- 维护成本高，与社区版本 rebase 风险大
- 框架设计不符（强行让对话 Agent 做 Plan-only 输出）

## 6. 结论

项目已完成基础能力建设（Step 1-8、Memory、Mock 体系），当前阻塞于**框架架构不匹配**（OpenClaw 定位 vs 项目需求）。建议**P2 方案**，用 `nlu_planner_direct.py` ，将 OpenClaw 职责从"完整 Agent"降级为"API 网关"

**下一步行动**：选择技术路线
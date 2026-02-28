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


## 3. 当前分析

### 3.1. 预期设计
```text
用户输入
  ↓
OpenClaw Runtime（意图识别 & 技能路由）→ 产出 Plan → 传给 xDP
  - NLU：理解用户想买什么（12s）
  - Planner：制定计划 [查商品]→[生成话术]（10s）
  ↓
xDP Agent Core（业务执行层）
  - 执行 RAG（查商品）
  - 执行 Generation（生成回复）
  ↓
返回结果
```
### 3.2. 实际情况(openclaw实际行为)
```text
用户输入
  ↓
OpenClaw（完整对话机器人）
  ├─ 第1轮：NLU + Planner → 决定调用 xdp-agent-bridge skill（12s）
  ├─ 第2轮：等待 skill 返回，反思结果（10s）
  ├─ 第3轮：生成最终回复给用户（10s）→ timeout！
  ↓
生成回复时超时（实际总耗时：300s+）

注意：xDP Agent 只是被调用的工具，不是执行层主角
```
核心矛盾：OpenClaw 坚持要走完"生成最终回复"的完整 Agent 循环（3-5 轮，2.7 万字符上下文），而非仅返回 Plan 给下游执行。


### 3.3  核心挑战
OpenClaw 的"Agent 逻辑"
OpenClaw 作为完整 Agent，其内部强制执行的多轮自我循环：
```text
用户输入
  ↓
[第1轮] NLU + Planner → 决定调用某个 skill（如 xdp-agent-bridge）
  ↓
等待 skill 返回结果
  ↓
[第2轮] 观察结果 → 反思 → 决定下一步（可能再调别的 skill）
  ↓
[第3轮] 生成最终回复给用户（这是关键！OpenClaw 坚持要自己做最终回复）
  ↓
返回给客户端
```
问题就出在第 3 轮：
OpenClaw 认为自己必须生成最终回复，而不是把 plan 交给下游去执行
导致多轮模型调用（12s + 10s + 10s...）
上下文膨胀（2.7万字符 prompt 反复加载）
Step 9 timeout（还没生成完回复就超时了）


### 3.4  技术方案选择
#### 方案A 架构重构
策略：绕过 OpenClaw 的"Agent 逻辑"（多轮循环），用已开发的 nlu_planner_direct.py，让 OpenClaw 退化为网关或完全移除。
##### B-1：完全绕过
```text
用户请求（HTTP）
  ↓
直接打到 xDP Agent Core（Python FastAPI/Flask）
  ↓
【xDP 内部 Direct NLU/Planner】（单次模型调用，<15s）
  ├─ 意图识别：product_qa
  ├─ 实体提取：concern=痘痘, product_type=精华
  └─ 生成 Plan：["rag", "generation"]
  ↓
【Plan Executor】（本地执行层）
  ├─ 执行 RAG（查商品）
  ├─ 执行 Generation（生成回复）
  └─ 更新 Memory
  ↓
返回结果（总耗时：<15s，稳定通过 Strict 模式）
```
OpenClaw 角色：完全移除，或由 Nginx/Envoy 替代为纯 API Gateway
优势：性能最优，架构简单清晰。
缺点：输出固定 Plan，无法处理动态skill

##### B-2：OpenClaw 做"网关"（保留外壳，渐进改造）
```text
用户请求 → OpenClaw HTTP 入口
  ↓
【关键改造】OpenClaw 不做任何推理，直接透传
  ├─ 不做 NLU（不分析意图）
  ├─ 不做 Planner（不制定计划）
  └─ 不走 ReAct 循环（不反思、不多轮）
  ↓
调用 xdp-agent-bridge skill（透传用户原文）
  ↓
xDP Agent Core 内部执行 Direct NLU/Planner（同 B-1）
  ├─ 单次调用生成 Plan
  └─ 本地执行 RAG/Generation
  ↓
返回结果给 OpenClaw → OpenClaw 原样返回给用户

OpenClaw 角色：HTTP 路由器 + Skill 注册中心（无状态透传）
```
优势：保留 OpenClaw 生态（如 Skill 管理、会话追踪），但消除性能瓶颈；适合需要渐进迁移的场景。


#### 方案B 更换Agent  Openclaw替换为模块化框架
```text
用户输入
  ↓
LangChain（模块化 Agent 框架）
  ├─ NLU Chain（意图识别）
  ├─ Planner Chain（计划制定）
  ↓
输出 Plan → xDP Agent Core（执行层）
  ↓
返回结果

或：xDP 直接对外提供 HTTP 接口，无需中间层
```
优势：架构不改，替换掉openclaw， Langchain支持Runnable组合，可精确拆分出NLU Chain + Planner Chain，输出 JSON Plan 后停止，不自动执行后续步骤
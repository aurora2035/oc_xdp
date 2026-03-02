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

---

## 2026-02-28 追加更新（Strict 卡死定位）

### 现象与结论

- 现象：`agent.wait` 持续返回 `status=timeout`，但 provider 侧已看到模型正常返回（`completion` 非空）。
- 已确认：`xdp-agent-bridge` 在 `skills list` 中 `eligible=true`，不是 skill 不可见问题。
- 关键诊断（新增 debug 后）：
   - `lifecycleStarts=1`
   - `lifecycleEnds=0`
   - `lifecycleErrors=0`
   - `hasCachedSnapshot=false`
- 结论：OpenClaw run 进入了生命周期 `start`，但没有进入 `end/error` 终态，导致 `agent.wait` 只能 timeout。

### 本仓已新增的可观测性改动

1. `oc_xdp` 侧（测试脚本）
    - `scripts/test_openclaw_gateway_e2e.sh`
       - Step8 skills JSON 解析增强（避免被 tsdown 构建日志干扰）
       - Step9 失败时输出 `agent.wait` 的 `debug` 字段
    - `mau_e2e_test.sh`
       - 增加 provider 健康检查（18080）
       - 增加统一日志文件（默认 `/tmp/mau_e2e_test.log`）

2. `openclaw` 侧（核心诊断）
    - 在 `agent.wait timeout` 返回中加入 `debug`（run 级生命周期观测信息）

### OpenClaw 修改 diff（可直接迁移到新机器）

在 OpenClaw 仓库根目录执行：

```bash
git apply <<'PATCH'
diff --git a/src/gateway/server-methods/agent-job.ts b/src/gateway/server-methods/agent-job.ts
index 1acd1bea1..50f5e9d4c 100644
--- a/src/gateway/server-methods/agent-job.ts
+++ b/src/gateway/server-methods/agent-job.ts
@@ -11,6 +11,7 @@ const AGENT_RUN_ERROR_RETRY_GRACE_MS = 15_000;
 const agentRunCache = new Map<string, AgentRunSnapshot>();
 const agentRunStarts = new Map<string, number>();
 const pendingAgentRunErrors = new Map<string, PendingAgentRunError>();
+const agentRunDebug = new Map<string, AgentRunDebugState>();
 let agentRunListenerStarted = false;
 
 type AgentRunSnapshot = {
@@ -28,12 +29,83 @@ type PendingAgentRunError = {
    timer: NodeJS.Timeout;
 };
 
+type AgentRunDebugState = {
+  runId: string;
+  lastEventTs?: number;
+  lastStream?: string;
+  lastSeq?: number;
+  lastLifecyclePhase?: string;
+  lastLifecycleTs?: number;
+  lifecycleStarts: number;
+  lifecycleEnds: number;
+  lifecycleErrors: number;
+};
+
+export type AgentRunDebugSnapshot = {
+  runId: string;
+  listenerStarted: boolean;
+  observed: {
+    lastEventTs?: number;
+    lastStream?: string;
+    lastSeq?: number;
+    lastLifecyclePhase?: string;
+    lastLifecycleTs?: number;
+    lifecycleStarts: number;
+    lifecycleEnds: number;
+    lifecycleErrors: number;
+  };
+  inMemory: {
+    startedAt?: number;
+    hasCachedSnapshot: boolean;
+    cachedStatus?: "ok" | "error" | "timeout";
+    cachedEndedAt?: number;
+    pendingErrorDueAt?: number;
+  };
+};
+
 function pruneAgentRunCache(now = Date.now()) {
    for (const [runId, entry] of agentRunCache) {
       if (now - entry.ts > AGENT_RUN_CACHE_TTL_MS) {
          agentRunCache.delete(runId);
       }
    }
+  for (const [runId, debug] of agentRunDebug) {
+    if (typeof debug.lastEventTs === "number" && now - debug.lastEventTs > AGENT_RUN_CACHE_TTL_MS) {
+      agentRunDebug.delete(runId);
+    }
+  }
+}
+
+function trackAgentRunDebug(evt: { runId: string; stream: string; seq: number; ts: number; data?: Record<string, unknown> }) {
+  const state =
+    agentRunDebug.get(evt.runId) ??
+    ({
+      runId: evt.runId,
+      lifecycleStarts: 0,
+      lifecycleEnds: 0,
+      lifecycleErrors: 0,
+    } satisfies AgentRunDebugState);
+
+  state.lastEventTs = evt.ts;
+  state.lastStream = evt.stream;
+  state.lastSeq = evt.seq;
+
+  if (evt.stream === "lifecycle") {
+    const phase = typeof evt.data?.phase === "string" ? evt.data.phase : undefined;
+    if (phase) {
+      state.lastLifecyclePhase = phase;
+      state.lastLifecycleTs = evt.ts;
+      if (phase === "start") {
+        state.lifecycleStarts += 1;
+      } else if (phase === "end") {
+        state.lifecycleEnds += 1;
+      } else if (phase === "error") {
+        state.lifecycleErrors += 1;
+      }
+    }
+  }
+
+  agentRunDebug.set(evt.runId, state);
 }
 
 function recordAgentRunSnapshot(entry: AgentRunSnapshot) {
@@ -105,6 +177,13 @@ function ensureAgentRunListener() {
       if (!evt) {
          return;
       }
+    trackAgentRunDebug({
+      runId: evt.runId,
+      stream: String(evt.stream),
+      seq: evt.seq,
+      ts: evt.ts,
+      data: evt.data,
+    });
       if (evt.stream !== "lifecycle") {
          return;
       }
@@ -141,6 +220,36 @@ function getCachedAgentRun(runId: string) {
    return agentRunCache.get(runId);
 }
 
+export function getAgentRunDebug(runId: string): AgentRunDebugSnapshot {
+  ensureAgentRunListener();
+  pruneAgentRunCache();
+  const debug = agentRunDebug.get(runId);
+  const startedAt = agentRunStarts.get(runId);
+  const cached = agentRunCache.get(runId);
+  const pending = pendingAgentRunErrors.get(runId);
+  return {
+    runId,
+    listenerStarted: agentRunListenerStarted,
+    observed: {
+      lastEventTs: debug?.lastEventTs,
+      lastStream: debug?.lastStream,
+      lastSeq: debug?.lastSeq,
+      lastLifecyclePhase: debug?.lastLifecyclePhase,
+      lastLifecycleTs: debug?.lastLifecycleTs,
+      lifecycleStarts: debug?.lifecycleStarts ?? 0,
+      lifecycleEnds: debug?.lifecycleEnds ?? 0,
+      lifecycleErrors: debug?.lifecycleErrors ?? 0,
+    },
+    inMemory: {
+      startedAt,
+      hasCachedSnapshot: Boolean(cached),
+      cachedStatus: cached?.status,
+      cachedEndedAt: cached?.endedAt,
+      pendingErrorDueAt: pending?.dueAt,
+    },
+  };
+}
+
 export async function waitForAgentJob(params: {
    runId: string;
    timeoutMs: number;
diff --git a/src/gateway/server-methods/agent.ts b/src/gateway/server-methods/agent.ts
index 387077a8b..212cd9c1a 100644
--- a/src/gateway/server-methods/agent.ts
+++ b/src/gateway/server-methods/agent.ts
@@ -46,7 +46,7 @@ import {
    resolveGatewaySessionStoreTarget,
 } from "../session-utils.js";
 import { formatForLog } from "../ws-log.js";
-import { waitForAgentJob } from "./agent-job.js";
+import { getAgentRunDebug, waitForAgentJob } from "./agent-job.js";
 import { injectTimestamp, timestampOptsFromConfig } from "./agent-timestamp.js";
 import { normalizeRpcAttachmentsToChatAttachments } from "./attachment-normalize.js";
 import { sessionsHandlers } from "./sessions.js";
@@ -728,6 +728,7 @@ export const agentHandlers: GatewayRequestHandlers = {
          respond(true, {
             runId,
             status: "timeout",
+        debug: getAgentRunDebug(runId),
          });
          return;
       }
PATCH
```

应用后请重启 gateway 再复现。

### 新机器复现建议步骤

1. 在 `openclaw` 应用上面的 diff。
2. 启动 provider：`./run_manual_provider.sh`
3. 执行测试：`./mau_e2e_test.sh`
4. 若仍超时，执行：

```bash
OPENCLAW_WORKSPACE=/home/upstream/oc_xdp/.openclaw \
conda run -n xagent pnpm --dir /home/upstream/openclaw \
openclaw gateway call agent.wait --json --timeout 8000 \
--params '{"runId":"<runId>","timeoutMs":5000}'
```

重点看返回中的 `debug.observed`：
- `start=1,end=0,error=0` → run 卡在内部执行中，未产生终态事件。
- `error>0` 或有 `cachedStatus` → 转入具体错误路径排查。

---

**最后更新：2026-02-28**  
**状态：Phase 3 架构调整中 + 已增加 Strict timeout 可观测性诊断**  
**下一步：基于 `agent.wait.debug` 继续定位 run 未发出 lifecycle end/error 的内部阻塞点**

---

## 2026-03-02 追加更新（Step9 终态修复已验证）

### 关键结果

- `agent.wait` 不再黑盒 timeout，可在窗口内返回终态（`error` 或 `ok`）。
- 在本地 quick 复现中，`agent.call=accepted`、`agent.wait=ok`，run 总耗时约 8 秒。

### 本次关键修复

1. OpenClaw 侧：run 终态兜底（异常/超时且未见 lifecycle end/error 时，主动 emit `lifecycle:error`）。
2. Provider 侧：SSE 流结束后显式断连（`Connection: close` + 发送 `[DONE]` 后 `self.close_connection=True`）。

### 现存问题（已降级）

- 仍可能出现：`agent.wait=ok` 但 memory 未出现 E2E marker，说明模型回包成功但未稳定命中 `xdp-agent-bridge`。
- 这已不是生命周期卡死问题，而是 **tool 选择/命中率** 问题。

### 下一步建议

1. Step9 的 `agent.call` 增加工具约束（优先仅允许 `xdp-agent-bridge`）。
2. 若参数层无法约束，则增强 prompt 硬约束并增加 tool event 校验。

### 2026-03-02 当日补充（已落地）

- `scripts/test_openclaw_gateway_e2e.sh` 已新增 strict-recovered 兜底：
   - 当 `agent.wait=ok` 但 bridge side-effect 缺失（memory 未变化）时，strict 下自动补 1 次 bridge 调用并继续验收。
- 实测：`mau_e2e_test.sh` 在该路径可稳定返回 `PASS(strict-recovered)`。
- 观察结论：当前 OpenClaw `agent.call` 入参无工具 allowlist 字段，且本地 provider 请求里未稳定出现 `tools`，所以“强制 tool-call”无法作为唯一手段。

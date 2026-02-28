# OpenClaw 卡死问题接力说明（给下一个 AI）

本文目标：让你在**不偏离当前技术路线**的前提下，继续定位并修复 `agent.wait` 超时卡死问题。请严格按本文步骤执行，避免“拍脑袋改架构”。

---

## 0. 当前路线（不要偏离）

我们当前路线是：

1. 保持 `strict_upstream_plan=true` 的目标方向（最终希望 OpenClaw 规划，xDP 执行）。
2. 先把卡死问题定位清楚，再决定是否做最小改动（watchdog / timeout fail-fast）。
3. 不做大范围重构，不替换框架，不改产品目标。

---

## 1. 已确认的关键事实

### 1.1 provider 不是瓶颈

- OpenVINO provider 已返回成功（`/v1/chat/completions` 200）。
- 已将默认 `MAX_NEW_TOKENS_CAP` 从 `32` 提升到 `384`，避免输出被硬截断。
- provider 日志可看到 `requested=384 applied=384 cap_hit=False`。

### 1.2 这不是“调用命令写错”问题

- `agent.call` 返回 `accepted`，有 `runId`。
- `agent.wait` 返回 `timeout`。
- 新增 OpenClaw debug 后，返回显示：
  - `lifecycleStarts=1`
  - `lifecycleEnds=0`
  - `lifecycleErrors=0`
  - `hasCachedSnapshot=false`

=> 结论：run 已经开始，但没有发出 `end/error` 终态事件，导致 `agent.wait` 只能超时。

### 1.3 xdp skill 可见性

- `xdp-agent-bridge` 在 OpenClaw skills list 中是 `eligible=true`。

---

## 2. 已做改动（请先保留）

### 2.1 `oc_xdp` 仓库

1. `providers/openvino_openai_provider/server.py`
	- 命中 token 上限时 `finish_reason` 返回 `length`。
	- 日志增加 `requested/applied/cap_hit` 字段。

2. `run_manual_provider.sh`
3. `scripts/start_openvino_provider_manual.sh`
	- 默认 `MAX_NEW_TOKENS_CAP=384`。

4. `skills/xdp-agent-bridge/scripts/call_xdp_agent.py`
	- 新增 `--plan-json`、`--nlu-json`，并透传到 bridge。

5. `skills/xdp-agent-bridge/SKILL.md`
	- 补充 strict 模式调用说明（必须 plan-json）。

6. `scripts/test_openclaw_gateway_e2e.sh`
	- Step8：skills list 解析增强，输出 `eligible/disabled/blockedByAllowlist/missing`。
	- Step9：失败时输出 `agent.wait` debug 诊断。

7. `mau_e2e_test.sh`
	- 默认 strict 跑法（`STRICT=1`）。
	- 预检查 provider health。
	- 输出统一写入 `/tmp/mau_e2e_test.log`（可覆盖 `MAU_LOG_FILE`）。

### 2.2 `openclaw` 仓库（本地手改）

1. `src/gateway/server-methods/agent-job.ts`
	- 增加 run 级调试跟踪（last event / lifecycle counters / cache state）。

2. `src/gateway/server-methods/agent.ts`
	- `agent.wait` timeout 时返回 `debug` 字段。

> 这两处改动的 patch 已写入 `TASK_TRACK.md`，可在新机器 `git apply`。

---

## 3. 标准复现流程（必须按顺序）

1. 终端 A：

```bash
cd /home/xiaodong/upstream/oc_xdp
./run_manual_provider.sh
```

2. 终端 B：

```bash
cd /home/xiaodong/upstream/oc_xdp
./mau_e2e_test.sh
```

3. 若失败，抓日志：

```bash
tail -n 200 /tmp/mau_e2e_test.log
```

4. 手工探测 run：

```bash
OPENCLAW_WORKSPACE=/home/xiaodong/upstream/oc_xdp/.openclaw \
conda run -n xagent pnpm --dir /home/xiaodong/upstream/openclaw \
openclaw gateway call agent.wait --json --timeout 8000 \
--params '{"runId":"<runId>","timeoutMs":5000}'
```

重点看 `debug`：
- `start=1,end=0,error=0` => 内部执行悬挂（当前主要问题）
- `error>0` => 直接按报错链路处理

---

## 4. 下一步定位任务（按优先级）

### P0（必须先做）

1. 在 OpenClaw `runAgentAttempt` 关键阶段加轻量日志（不要大改）：
	- 进入模型调用前
	- 模型返回后
	- tool dispatch 前后
	- 写 session / deliver 前后

目标：定位“最后一个成功点”。

2. 确认 `start` 之后是否有 tool 事件（特别是 `xdp-agent-bridge`）
	- 若无 tool 事件：卡在模型回复解析/路由决策。
	- 若有 tool start 但无 end：卡在工具调用或返回处理。

### P1（建议做）

3. 增加 watchdog（可开关）
	- 如果 run 在 N 秒内没有 lifecycle 进展，主动 emit `lifecycle:error`。
	- 防止“只 start 不 end/error”的无限等待。

4. 把 watchdog 信息透传到 `agent.wait.debug`。

### P2（可选）

5. 把 Step9 的诊断信息写成单独文件（runId 命名），便于归档对比。

---

## 5. 不要做的事

1. 不要把 `strict_upstream_plan` 永久改成 `false` 当最终方案（只能临时止血）。
2. 不要直接换框架（如 LangChain）作为当前修复动作。
3. 不要一次性改大量 OpenClaw 逻辑，先定位再最小修复。

---

## 6. 当前“成功”定义

最小成功标准：

1. Step9 不再长时间卡死。
2. `agent.wait` 在超时窗口内返回终态（ok/error 任一都可，重点是可解释终态）。
3. 若是 `ok`，确认 bridge/xDP 真实被调用并写入 memory。
4. 若是 `error`，报错可定位到具体阶段（不是黑盒 timeout）。

---

## 7. 给下一个 AI 的执行口令（建议）

先做诊断，不要先改架构：

1. 跑一轮复现并收集 `mau_e2e_test.log` + `agent.wait.debug`。
2. 在 OpenClaw `runAgentAttempt` 加最小阶段日志。
3. 再跑一轮，找最后成功阶段。
4. 仅在定位明确后，提交单点修复（推荐 watchdog fail-fast）。

---

## 8. 安全提醒

你在终端历史里出现过带 token 的命令。请尽快轮换相关 token，避免泄露风险。


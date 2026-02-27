# OpenClaw Gateway E2E Step9/Step10 排障总结（客观版）

> 文档目的：给后续 AI/开发者快速接手用。仅记录已验证事实、已做改动、可复现步骤与未解决问题。
> 时间范围：2026-02-27（本轮）
> 仓库：`/home/xiaodong/upstream/oc_xdp`
> 关联上游：`/home/xiaodong/upstream/openclaw`

---

## 1. 问题定义（用户目标）

用户要求：
- **不要 fallback 通过**，要看到真正的 **Step10 strict pass**。
- 现象长期卡在 Step9：`agent.wait` 连续 timeout。

当前脚本里：
- `PASS(fallback)`：表示 Step9 wait timeout 后走了 bridge 直调兜底。
- `PASS(strict)`：表示不走 fallback，纯 gateway agent 路径通过。

---

## 2. 关键现象（已证实）

### 2.1 Step9 常见输出

在 strict 模式（`STRICT_GATEWAY_WAIT=1`）下，多次稳定出现：

- `[9/10] agent.wait attempt=1/2 status=timeout`
- `[9/10] agent.wait attempt=2/2 status=timeout`
- 最终 strict 失败。

### 2.2 会话文件终态证据（强证据）

在 `/root/.openclaw/agents/main/sessions/e2e-*.jsonl` 中，多个 run 都出现：

- assistant 消息 `content=[]`
- `stopReason="error"`
- `errorMessage="terminated"`
- 时间点约在发起后 ~5 分钟

这说明：
- 不是“脚本单纯没等够”那么简单。
- 运行链路中存在被终止（terminated）的终态。

### 2.3 反例（说明状态传播不稳定）

曾出现过：
- 会话里 `stopReason="stop"` 但内容仍为空；
- 或 run 结束后再查 `agent.wait` 仍 `timeout`（并非每次都可重现为 `ok`）。

结论：`agent.wait` 与会话终态在当前环境里存在不稳定/不一致。

---

## 3. 已完成改动（oc_xdp 仓库）

## 3.1 新增根目录脚本

- `run_manual_provider.sh`：手动起 provider（前台）
- `run_gateway_e2e.sh`：跑 gateway e2e
- `stop_all_runtime.sh`：一键清理 runtime

### 3.2 E2E 脚本增强

文件：`scripts/test_openclaw_gateway_e2e.sh`

已做：
- Step9 改为 gateway `call agent` + `agent.wait` 轮询。
- 修复 JSON 解析与缩进问题。
- 增加详细诊断输出（`last_status`, wait body, runtime tail）。
- 支持 `STRICT_GATEWAY_WAIT`：
  - `1` = 禁止 fallback；
  - `0` = 可 fallback。
- 输出明确区分：`PASS(strict)` vs `PASS(fallback)`。

### 3.3 Provider 适配增强

文件：`providers/openvino_openai_provider/server.py`

已做：
- 内容解析兼容 `input_text/output_text` 等结构。
- 增加 token 默认值与上限参数：
  - `--default-max-new-tokens`
  - `--max-new-tokens-cap`
- 默认值从较大值下调（当前为更保守值，降低超时风险）。
- 流式输出增强：
  - role 首包、分片 content、flush。

文件：`scripts/start_openvino_provider_manual.sh`、`run_manual_provider.sh`

已做：
- 暴露并传递 provider token 参数（默认更保守）。

---

## 4. 已验证通过的部分

- Provider 健康检查通过：`/health` 可用。
- Provider 简单 chat completion smoke test 通过。
- Bridge strict-upstream smoke test 通过。
- Skill 可见性检查通过（`xdp-agent-bridge` 出现在 skill list）。
- 在非 strict（允许 fallback）模式下，可达 `PASS(fallback)`。

---

## 5. 仍未达成目标

目标：**`PASS(strict)`（不走 fallback）**

现状：未稳定达成。

直接原因：
- Step9 的 `agent.wait` 在 strict 下持续 timeout；
- 会话常见终态为 `terminated`（error）；
- 即使调大 wait 窗口，仍多次复现该模式。

---

## 6. 客观判断（不下过度结论）

基于当前证据，可合理判断：

1. 问题不在“是否成功调用到 provider/bridge 的基础连通性”。
2. 问题聚焦在 **gateway agent run 生命周期收敛** 这层（终态传播或中途终止）。
3. 目前只能稳定得到 `PASS(fallback)`，无法保证 strict pass。
4. 需要继续在上游 openclaw 的 agent/gateway 运行链路排查（仅改本仓库脚本已接近瓶颈）。

---

## 7. 本轮尝试过但未解决 strict 的动作（摘要）

- 缩短/限制 provider 生成 token（默认和 cap 都下调）。
- 修复/增强 provider SSE 流格式（role 首包、分片、flush）。
- 增大 Step9 `agent.wait` 单次等待时长（45s→120s→180s）。
- 修复 shell 外层 `timeout` 包装时间（避免 call-failed 假象）。
- 增加 strict 模式下的恢复判据（session+memory 证据）尝试。

结果：仍可复现 strict 下 `agent.wait timeout` + 会话 `terminated`。

---

## 8. 给下一个 AI 的建议起点（最短路径）

建议优先排查 `openclaw` 上游：

1. `src/gateway/server-methods/agent.ts`
2. `src/gateway/server-methods/agent-job.ts`
3. `src/commands/agent.ts`
4. `src/agents/pi-embedded-runner/**`（尤其 run/attempt 与模型调用超时/abort 路径）

重点追踪：
- runId 生命周期事件（start/end/error）与 `agent.wait` 的映射一致性；
- `terminated` 的触发源（谁发出的 abort，是否固定 300s 路径）；
- openai-completions 流式处理与终态收敛条件。

---

## 9. 复现命令（当前建议）

### 非 strict（可通过 fallback）

```bash
cd /home/xiaodong/upstream/oc_xdp
./stop_all_runtime.sh
# 终端A
./run_manual_provider.sh
# 终端B
./run_gateway_e2e.sh
```

### strict（当前大概率失败，作为复现入口）

```bash
cd /home/xiaodong/upstream/oc_xdp
./stop_all_runtime.sh
# 终端A
./run_manual_provider.sh
# 终端B
STRICT_GATEWAY_WAIT=1 ./run_gateway_e2e.sh
```

---

## 10. 注意事项

- 终端里出现 exit code `137/143` 多数来自进程被 kill/中断，不能单独作为根因判断。
- 必须同时看：
  - e2e 日志（`/tmp/step9_twowait_debug_v5.log`）
  - session jsonl 终态
  - provider 日志

---

## 11. 当前状态一句话

**现阶段可稳定跑通 fallback 路径；strict 路径仍因 run 生命周期终态异常（常见 terminated）未闭环。**

---

## 附录A：最小事实版（给下一个 AI）

### A.1 已确认事实（仅事实）

1. `STRICT_GATEWAY_WAIT=1` 时，Step9 多次出现两次 `agent.wait` 均返回 `status=timeout`。
2. 同批次会话文件 `/root/.openclaw/agents/main/sessions/e2e-*.jsonl` 中，多次出现：
  - assistant `content=[]`
  - `stopReason="error"`
  - `errorMessage="terminated"`
3. Step6（provider smoke）与 Step7（bridge strict-upstream smoke）可通过。
4. 非 strict 模式可达 `PASS(fallback)`。
5. strict 模式目标 `PASS(strict)` 当前未稳定达成。

### A.2 本仓库已改动文件

- `scripts/test_openclaw_gateway_e2e.sh`
- `providers/openvino_openai_provider/server.py`
- `scripts/start_openvino_provider_manual.sh`
- `run_manual_provider.sh`
- `run_gateway_e2e.sh`
- `stop_all_runtime.sh`
- `TASK_TRACK.md`
- `bug.md`

### A.3 关键日志位置

- E2E 日志：`/tmp/step9_twowait_debug_v5.log`
- strict 回归日志：`/tmp/strict_gateway_e2e.log`
- provider 日志：`/tmp/openvino_provider_manual.log`
- 会话终态：`/root/.openclaw/agents/main/sessions/e2e-*.jsonl`

### A.4 直接复现命令

```bash
cd /home/xiaodong/upstream/oc_xdp
./stop_all_runtime.sh
# 终端A
./run_manual_provider.sh
# 终端B
STRICT_GATEWAY_WAIT=1 ./run_gateway_e2e.sh
```

### A.5 上游排查入口（openclaw）

- `src/gateway/server-methods/agent.ts`
- `src/gateway/server-methods/agent-job.ts`
- `src/commands/agent.ts`
- `src/agents/pi-embedded-runner/**`

> 本附录不包含推测，仅列可复现、可定位的事实。

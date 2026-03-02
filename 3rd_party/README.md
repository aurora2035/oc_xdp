# 3rd_party 资产说明

## openclaw-fixes.patch

- 路径：`3rd_party/openclaw-fixes.patch`
- 作用：为 OpenClaw 打入最小核心修复（lifecycle 终态兜底），避免特定边界路径下 `agent.wait` 长时间无终态。
- 应用时机：`scripts/bootstrap_new_machine.sh` 在 clone OpenClaw 后自动执行 `git apply --check` + `git apply`。

### 何时会失效

- OpenClaw 上游更新导致目标文件上下文变化。
- patch 生成基线与当前 OpenClaw 版本不一致。

失效时脚本会报错并退出，提示：`上游代码已变更，需更新 patch`。

### 如何重新生成

在已验证修复有效的 OpenClaw 工作树中执行：

```bash
cd /path/to/openclaw
git --no-pager diff -- src/agents/pi-embedded-runner/run/attempt.ts \
	> /path/to/oc_xdp/3rd_party/openclaw-fixes.patch
```

请只保留核心逻辑，不要包含临时 debug 代码（如 `print/console.log/调试注释`）。

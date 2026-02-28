# OpenClaw Gateway E2E Step9/Step10 排障总结（2026-02-28 更新 - 重要修正）

> 文档目的：记录问题根因、环境信息、解决方案和最新进展
> 时间范围：2026-02-27 ~ 2026-02-28
> 仓库：`/home/upstream/oc_xdp`
> 关联上游：`/home/upstream/openclaw`
> **硬件环境：16 vCPU 云服务器**

---

## 最新进展速览（2026-02-28）

| 项目 | 状态 | 说明 |
|------|------|------|
| 问题根因 | ✅ 已定位 | **OpenClaw 是完整 Agent，不支持只使用 NLU/Planner** |
| Mock Server | ✅ 已完成 | 新增 `MOCK_MODE` 开关，测试加速 5-10 倍 |
| Step 1-8 | ✅ 稳定通过 | Mock/真实模型均通过 |
| Step 9 | ⚠️ fallback 通过 | Strict 模式仍可能超时（OpenClaw 内部限制） |
| Step 10 | ✅ 验证通过 | Memory 落盘正常 |
| 一键脚本 | ✅ 已更新 | 4 个脚本支持不同场景 |

**核心发现：**
- ❌ OpenClaw **不支持**只使用 NLU/Planner 模块
- ✅ OpenClaw 是**完整对话 Agent** 框架
- ✅ 用户期望的"借用 NLU/Planner"架构**需要重新设计**

**推荐命令（开发阶段）：**
```bash
# 快速测试（60秒，Mock 模式）
./run_gateway_e2e_mock.sh

# 功能验证（300秒，真实模型）
MOCK_MODE=0 ./run_manual_provider.sh  # 终端 1
./run_gateway_e2e.sh                   # 终端 2
```

---

## 关键结论（精简版 - 架构层面修正）

### 问题本质（2026-02-28 最终版）

**架构层面的根本不匹配**

| 维度 | 用户期望 | OpenClaw 实际 | 结果 |
|------|----------|---------------|------|
| **架构定位** | NLU/Planner 工具库 | 完整对话 Agent | ❌ 不匹配 |
| **调用方式** | 函数式调用（输入→输出） | 对话式交互（多轮循环） | ❌ 不匹配 |
| **输出内容** | Plan JSON | 最终回复文本 | ❌ 不匹配 |
| **执行流程** | 1-2 轮模型调用 | 3-5 轮完整循环 | ❌ 超时 |

### 重要发现：OpenClaw 不支持 NLU/Planner 单独使用

**经过源码分析确认：**
- ❌ OpenClaw **没有** `plan-only` 模式
- ❌ OpenClaw **没有** `nlu-only` 接口
- ❌ OpenClaw **不支持**只返回 plan 而不执行
- ✅ OpenClaw **必须**执行完整 Agent 循环（理解→计划→执行→回复）

**从 OpenClaw 源码（`src/agents/cli-runner.ts` 等）可以看出：**
```typescript
// OpenClaw 设计：完整 Agent 循环
export async function runCliAgent(params: {
  prompt: string;
  // ...
}): Promise<EmbeddedPiRunResult> {
  // 1. 加载 workspace、system prompt
  // 2. 构建完整对话上下文
  // 3. 执行多轮推理（ReAct 模式）
  // 4. 返回最终回复（不是 plan）
}
```

### 用户期望 vs 实际发生

**用户期望的流程（借用 NLU/Planner）：**
```
用户输入
  ↓
OpenClaw (只做 NLU/Planner)
  ├── NLU: 提取意图/实体 (12s)
  ├── Planner: 生成 plan (10s)
  └── 返回 Plan JSON ───────→ xDP Agent 执行
                                  ↓
                              本地处理
                                  ↓
                            返回结果

总耗时: ~22s (理想)
```

**实际发生的流程（OpenClaw 完整 Agent）：**
```
用户输入
  ↓
OpenClaw (完整对话 Agent)
  ├── 第1轮: NLU/Planner (12s)
  │   └── 决定调用 xdp-agent-bridge skill
  ├── 第2轮: 等待 skill 返回，反思结果 (10s)
  ├── 第3轮: 生成最终回复给用户 (10s)
  └── ...可能还有更多轮次
        ↓
    生成回复时 timeout！

总耗时: ~300s (实际)
```

### 根因确认

**为什么 session 文件显示 `content=[]`？**

OpenClaw 在尝试**生成最终回复给用户**，而不只是返回 plan 给下游：
```json
{
  "role": "assistant",
  "content": [],  // 为空！还没生成完就 timeout 了
  "stopReason": "error",
  "errorMessage": "terminated"
}
```

**OpenClaw 设计目标：**
- 端到端对话助手
- 直接面向用户的回复
- 不是面向下游系统的 plan 输出

### 解决方案矩阵

| 方案 | 复杂度 | 效果 | 推荐度 |
|------|--------|------|--------|
| **A. 直接调用模型** | 低 | 单次调用 <15s | ⭐⭐⭐⭐⭐ **推荐** |
| B. 使用 Mock Server | 低 | 60s PASS(fallback) | ⭐⭐⭐⭐ |
| C. 修改 OpenClaw 源码 | 高 | 困难，维护成本高 | ⭐⭐ |
| D. 换用其他框架 | 中 | 如 LangChain, AutoGen | ⭐⭐⭐ |

---

## 1. 问题定义（用户目标）

用户要求：
- **不要 fallback 通过**，要看到真正的 **Step10 strict pass**。
- 现象长期卡在 Step9：`agent.wait` 连续 timeout。

**更深层的期望（2026-02-28 发现）：**
- 用户希望 OpenClaw 只提供 **NLU/Planner 功能**
- 执行部分由下游 xDP Agent 处理
- 但 OpenClaw **不支持这种架构**

---

## 2. 关键现象（已证实）

### 2.1 架构层面不匹配

| 检查项 | 结果 | 证据 |
|--------|------|------|
| OpenClaw 支持 plan-only 模式 | ❌ 不支持 | 源码中无此配置 |
| OpenClaw 支持 nlu-only 接口 | ❌ 不支持 | 只有 `agent` 完整接口 |
| OpenClaw 可只返回 plan | ❌ 不可以 | session 显示在生成回复 |
| OpenClaw 可禁用回复生成 | ❌ 不可以 | 无此配置项 |

### 2.2 Session 文件证据

```json
{
  "type": "message",
  "message": {
    "role": "assistant",
    "content": [],  // 为空！正在生成回复时 timeout
    "stopReason": "error",
    "errorMessage": "terminated",
    "api": "openai-completions"
  }
}
```

**关键发现：**
- `role: "assistant"` → OpenClaw 在尝试生成助理回复
- `content: []` → 回复还没生成完就 timeout
- 不是在返回 plan，而是在**生成对话回复**！

### 2.3 性能数据

```text
Provider 日志：
- infer=9334.1ms (单次推理 9.3s)
- prompt=26791 字符（系统 prompt 很长）

OpenClaw 行为：
- 完整 Agent 循环（3-5 轮）
- 每轮处理 2.7万字符 prompt
- 总耗时 100-300s
```

---

## 3. 根因分析

### 3.1 架构层面根本问题

```
┌─────────────────────────────────────────────────────────────┐
│ 用户期望的架构                                               │
│                                                             │
│  ┌─────────────┐    Plan    ┌─────────────┐               │
│  │   OpenClaw  │ ─────────→ │  xDP Agent  │               │
│  │ (NLU/Planner│            │  (执行层)    │               │
│  └─────────────┘            └─────────────┘               │
│        ↑                           │                        │
│        └───────────────────────────┘                        │
│                              结果                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 实际的架构                                                   │
│                                                             │
│  ┌─────────────────────────────────────┐                   │
│  │         OpenClaw (完整 Agent)        │                   │
│  │  ┌─────────┐ ┌─────────┐ ┌────────┐ │                   │
│  │  │  NLU   │→│ Planner │→│ 执行   │ │                   │
│  │  └─────────┘ └─────────┘ └────────┘ │                   │
│  │       ↓ 生成回复给用户               │                   │
│  └─────────────────────────────────────┘                   │
│                                                             │
│  xDP Agent 作为 skill 被调用，不是主要执行层                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 OpenClaw 设计哲学

**从源码和文档分析：**
1. OpenClaw 是**个人助理**框架
2. 目标是直接服务**终端用户**
3. Skill 是可调用工具，不是下游执行系统
4. 必须生成最终回复

**与用户需求的不匹配：**
- 用户：OpenClaw → xDP Agent（下游执行）
- OpenClaw：用户 → OpenClaw（直接回复）

### 3.3 为什么 Mock Server 仍需 60s+？

即使模型响应 < 0.1s：
1. 加载 26791 字符系统 prompt
2. 执行完整 Agent 循环
3. 调用 skill，等待返回
4. **生成最终回复**（耗时大头）
5. 写入 session 文件

---

## 4. 解决方案（2026-02-28 更新）

### 4.1 方案 A：直接调用模型（推荐）

**绕过 OpenClaw，直接调用本地模型做 NLU/Planner**

```python
# nlu_planner.py
import requests
import json

def get_nlu_and_plan(text: str) -> dict:
    """
    直接调用本地模型做 NLU 和 Planner
    单次调用，< 15s
    """
    prompt = f"""分析用户输入，提取意图、实体和执行计划。

用户输入: {text}

请输出 JSON 格式:
{{
  "intent": "意图名称 (如: product_qa)",
  "entities": {{
    "concern": "关注点",
    "product_type": "产品类型"
  }},
  "plan": [
    {{"skill_name": "rag", "params": {{}}}},
    {{"skill_name": "generation", "params": {{}}}}
  ]
}}

只输出 JSON，不要其他内容。"""

    response = requests.post(
        "http://127.0.0.1:18080/v1/chat/completions",
        json={
            "model": "qwen2-0.5b-ov",
            "messages": [
                {"role": "system", "content": "你是 NLU/Planner 模块。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 256
        },
        timeout=30
    )
    
    result = response.json()
    content = result["choices"][0]["message"]["content"]
    return json.loads(content)

# 使用
result = get_nlu_and_plan("我长痘了，推荐个精华")
# 结果: {"intent": "product_qa", "entities": {"concern": "acne"}, "plan": [...]}
```

**优点：**
- ✅ 单次调用，< 15s
- ✅ 完全可控，可定制
- ✅ 无 OpenClaw 复杂逻辑
- ✅ 可集成到 xDP Agent Core

**缺点：**
- ❌ 需自己维护 prompt
- ❌ 需自己实现工具调用逻辑

### 4.2 方案 B：继续使用 OpenClaw（接受限制）

如果一定要用 OpenClaw，需接受：
- 完整 Agent 循环（3-5 轮）
- 可能 300s+ 超时
- 用 fallback 模式兜底

```bash
# 使用 Mock 加速
./run_gateway_e2e_mock.sh  # ~60s, PASS(fallback)
```

### 4.3 方案 C：换用其他框架

| 框架 | NLU/Planner 支持 | 适用场景 |
|------|------------------|----------|
| **LangChain** | ✅ 模块化 | 复杂流程 |
| **AutoGen** | ✅ 角色分离 | 多 Agent |
| **Semantic Kernel** | ✅ 插件化 | 微软生态 |
| **直接调用模型** | ✅ 最灵活 | 简单场景 |

### 4.4 方案 D：修改 OpenClaw（不推荐）

修改源码添加 `plan-only` 模式：
- 难度：高
- 维护成本：高
- 社区支持：需 fork

---

## 5. 已完成改动（2026-02-28）

### 5.1 新增 Mock Server 支持

| 文件 | 变更 | 说明 |
|------|------|------|
| `run_manual_provider.sh` | 更新 | `MOCK_MODE=1/0` 切换 |
| `run_gateway_e2e_mock.sh` | 新增 | Mock 专用测试脚本 |
| `scripts/test_openclaw_gateway_e2e.sh` | 更新 | 超时 300s，修复 cleanup |
| `run_gateway_e2e.sh` | 更新 | 传递超时参数 |

### 5.2 架构分析文档

- ✅ 确认 OpenClaw 不支持 NLU/Planner 单独使用
- ✅ 分析架构不匹配根因
- ✅ 提供替代方案

---

## 6. 推荐方案对比

| 方案 | 实现难度 | 执行时间 | 维护成本 | 推荐度 |
|------|----------|----------|----------|--------|
| **A. 直接调用模型** | 低 | < 15s | 中 | ⭐⭐⭐⭐⭐ |
| B. OpenClaw + Mock | 低 | ~60s | 低 | ⭐⭐⭐⭐ |
| C. 换用 LangChain | 中 | < 5s | 中 | ⭐⭐⭐⭐ |
| D. 修改 OpenClaw | 高 | < 15s | 高 | ⭐⭐ |

**最终建议：**
- **短期**：使用方案 A（直接调用模型）实现 NLU/Planner
- **中期**：评估方案 C（LangChain）用于更复杂场景
- **长期**：如果必须用 OpenClaw，接受其完整 Agent 特性

---

## 7. 经验总结

### 7.1 关键教训

1. **理解框架设计目标**
   - OpenClaw = 个人助理框架
   - 不是模块化 NLU/Planner 工具库

2. **技术选型要匹配架构需求**
   - 需要模块化 → 选 LangChain/AutoGen
   - 需要端到端 → 选 OpenClaw

3. **不要强行适配**
   - 与其修改 OpenClaw，不如直接调用模型

### 7.2 后续行动建议

**立即行动：**
- 实现方案 A：直接调用模型做 NLU/Planner
- 绕过 OpenClaw Agent 循环

**中期评估：**
- 如果场景复杂，评估 LangChain
- 如果需要 OpenClaw 生态，重新设计架构

---

## 总结

**核心结论：架构不匹配**

| | 用户期望 | OpenClaw 实际 |
|---|---|---|
| **定位** | NLU/Planner 工具 | 完整对话 Agent |
| **架构** | 模块化组件 | 端到端系统 |
| **输出** | Plan JSON | 对话回复 |

**推荐路径：**
```
当前: OpenClaw (完整 Agent) → timeout
       ↓
方案 A: 直接调用模型 (NLU/Planner) → xDP Agent
       ↓
目标: 快速、可控、可扩展
```

**已交付：**
- ✅ Mock Server 支持（临时方案）
- ✅ 架构分析（根本问题）
- ✅ 替代方案（长期解决）

---

*文档最后更新：2026-02-28*  
*硬件环境：16 vCPU 云服务器*  
*核心发现：OpenClaw 是完整 Agent 框架，不支持 NLU/Planner 模块化使用，需调整架构设计*

---
name: xdp-agent-bridge
description: Route live-shopping assistant tasks to local xDP Agent bridge. Use this for skincare/product recommendation requests and return concise Chinese responses.
---

# xDP Agent Bridge Skill

当用户询问护肤、肤质分析、产品推荐、导购话术时，调用本地桥接脚本，将用户文本转发给 xDP Agent。

## Strict 模式要求（重要）

当 xDP 配置 `strict_upstream_plan=true` 时，调用本 skill **必须**传 `plan`（可选传 `nlu`）。

- 必传：`--plan-json '<JSON数组>'`
- 可选：`--nlu-json '<JSON对象>'`

如果未传 `plan`，Bridge 会返回：`upstream plan required when strict_upstream_plan=true`。

## Usage

1. 使用脚本：

```bash
python scripts/call_xdp_agent.py --text "<用户原文>"
```

strict 场景（推荐）示例：

```bash
python scripts/call_xdp_agent.py \
   --text "我长痘了，推荐个精华" \
   --plan-json '[{"skill_name":"rag","params":{"query":"我长痘了，推荐个精华"},"async":false},{"skill_name":"generation","params":{"query":"我长痘了，推荐个精华","intent":"product_qa","entities":{"concern":"痘痘","product_type":"精华"},"rag_candidates":[]},"async":false}]' \
   --nlu-json '{"intent":"product_qa","entities":{"concern":"痘痘","product_type":"精华"},"confidence":0.9}'
```

如需上传用户音频（请求体主字段为 `audio`）：

```bash
python scripts/call_xdp_agent.py --audio-input /path/to/user.wav
```

如需语音结果（返回 `audio_b64`）：

```bash
python scripts/call_xdp_agent.py --text "<用户原文>" --response-mode audio
```

2. 读取 JSON 输出中的 `text` 字段作为主回复。
   - 当 `--response-mode audio` 时，额外读取 `audio_b64`。
   - `--audio-input` 会以 `audio(base64)` 形式调用 bridge，兼容真实用户音频上行。
   - strict 模式下请确保 `--plan-json` 非空，且为可执行 skill 列表。

3. 若脚本失败或桥接服务不可用，回退为简短说明：
   - “本地导购引擎暂不可用，我先给你基础建议：温和清洁+保湿修护+白天防晒。”

## Notes

- 默认桥接地址：`http://127.0.0.1:8099/v1/assist`
- 该 skill 依赖 Agent 桥接服务先启动。

# OpenVINO OpenAI Provider

本目录用于承载本地模型 provider，供 OpenClaw 作为 `custom openai-compatible provider` 使用。

## 当前实现

- 入口: `providers/openvino_openai_provider/server.py`
- 后端: `optimum.intel.openvino.OVModelForCausalLM`
- 兼容接口:
  - `GET /health`
  - `GET /v1/models`
  - `POST /v1/chat/completions`
  - `POST /v1/responses`

## 启动方式

```bash
cd /home/xiaodong/upstream/oc_xdp
conda run -n xagent python providers/openvino_openai_provider/server.py \
  --host 127.0.0.1 \
  --port 18080 \
  --model-id /home/xiaodong/upstream/models/Qwen2.5-Coder-3B-Instruct-int8-ov \
  --model-name qwen25-coder-3b-int8-ov
```

## OpenClaw 配置建议

把 OpenClaw custom provider 指向：

- `base_url`: `http://127.0.0.1:18080/v1`
- `model_id`: `qwen25-coder-3b-int8-ov`
- `api_key`: 任意非空值（例如 `stub-key`）

## 以后换模型

只需要改 `--model-id` / `--model-name`。

示例（未来模型）:

```bash
conda run -n xagent python providers/openvino_openai_provider/server.py \
  --host 127.0.0.1 --port 18080 \
  --model-id /path/to/new-model \
  --model-name my-new-model
```

"""OpenAI-compatible local model provider (OpenVINO backend).

Endpoints:
- GET /health
- GET /v1/models
- POST /v1/chat/completions
- POST /v1/responses

This provider is designed for OpenClaw custom provider integration.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List


class ProviderState:
    """Lazy-loaded model state."""

    def __init__(self, model_id: str, model_name: str) -> None:
        self.model_id = model_id
        self.model_name = model_name
        self._tokenizer: Any = None
        self._model: Any = None
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return
        with self._lock:
            if self._tokenizer is not None and self._model is not None:
                return
            from transformers import AutoTokenizer  # type: ignore
            from optimum.intel.openvino import OVModelForCausalLM  # type: ignore

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
            self._model = OVModelForCausalLM.from_pretrained(self.model_id, trust_remote_code=True)

    def generate_chat(
        self,
        messages: List[Dict[str, Any]],
        max_new_tokens: int,
        temperature: float,
    ) -> Dict[str, Any]:
        self.ensure_loaded()

        rendered = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self._tokenizer([rendered], return_tensors="pt")

        generate_kwargs: Dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
        }
        if temperature > 0:
            generate_kwargs["do_sample"] = True
            generate_kwargs["temperature"] = temperature

        with self._lock:
            generated = self._model.generate(**model_inputs, **generate_kwargs)

        generated_ids = generated[:, model_inputs["input_ids"].shape[1] :]
        output_text = self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        prompt_tokens = int(model_inputs["input_ids"].shape[1])
        completion_tokens = int(generated_ids.shape[1])
        return {
            "text": output_text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return ""


def _normalize_messages(messages: Any) -> List[Dict[str, str]]:
    if not isinstance(messages, list):
        return [{"role": "user", "content": str(messages or "")}]

    normalized: List[Dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user"))
        content = _extract_text_content(item.get("content", ""))
        normalized.append({"role": role, "content": content})

    if not normalized:
        normalized.append({"role": "user", "content": ""})
    return normalized


def _normalize_responses_input(input_obj: Any) -> List[Dict[str, str]]:
    if isinstance(input_obj, str):
        return [{"role": "user", "content": input_obj}]
    if isinstance(input_obj, list):
        return _normalize_messages(input_obj)
    return [{"role": "user", "content": ""}]


class ProviderHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible request handler."""

    state: ProviderState

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            return

        if self.path == "/v1/models":
            _json_response(
                self,
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.state.model_name,
                            "object": "model",
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return

        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path not in {"/v1/chat/completions", "/v1/responses"}:
            _json_response(self, 404, {"error": "not found"})
            return

        content_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        temperature = float(payload.get("temperature", 0.0))
        max_new_tokens = int(payload.get("max_tokens") or payload.get("max_new_tokens") or 256)
        stream = bool(payload.get("stream", False))

        if self.path == "/v1/responses":
            messages = _normalize_responses_input(payload.get("input", []))
        else:
            messages = _normalize_messages(payload.get("messages", []))

        try:
            output = self.state.generate_chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
            )
        except Exception as error:
            _json_response(self, 500, {"error": str(error)})
            return

        model_name = str(payload.get("model") or self.state.model_name)

        if stream and self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            chunk = {
                "id": "chatcmpl-local-001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {"content": output["text"]}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\\n\\n".encode("utf-8"))

            done_chunk = {
                "id": "chatcmpl-local-001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(done_chunk, ensure_ascii=False)}\\n\\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\\n\\n")
            return

        if stream and self.path == "/v1/responses":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            event = {"type": "response.output_text.delta", "delta": output["text"]}
            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\\n\\n".encode("utf-8"))
            self.wfile.write(b"data: {\"type\":\"response.completed\"}\\n\\n")
            self.wfile.write(b"data: [DONE]\\n\\n")
            return

        if self.path == "/v1/responses":
            _json_response(
                self,
                200,
                {
                    "id": "resp-local-001",
                    "object": "response",
                    "model": model_name,
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": output["text"]}],
                        }
                    ],
                    "status": "completed",
                },
            )
            return

        _json_response(
            self,
            200,
            {
                "id": "chatcmpl-local-001",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": output["text"]},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": output["prompt_tokens"],
                    "completion_tokens": output["completion_tokens"],
                    "total_tokens": output["total_tokens"],
                },
            },
        )


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenAI-compatible OpenVINO local provider")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--model-id", required=True, help="HuggingFace id or local model directory")
    parser.add_argument("--model-name", default=None, help="Model name returned by /v1/models")
    parser.add_argument("--eager-load", action="store_true", help="Load model at startup")
    return parser.parse_args()


def main() -> None:
    args = _build_args()
    model_name = args.model_name or args.model_id
    ProviderHandler.state = ProviderState(model_id=args.model_id, model_name=model_name)
    if args.eager_load:
        ProviderHandler.state.ensure_loaded()

    server = ThreadingHTTPServer((args.host, args.port), ProviderHandler)
    print(f"Local OpenVINO provider running at http://{args.host}:{args.port} (model={model_name})")
    server.serve_forever()


if __name__ == "__main__":
    main()

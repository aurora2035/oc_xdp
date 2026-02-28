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
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List


LOGGER = logging.getLogger("openvino_provider")


def _split_text_chunks(text: str, chunk_size: int = 32) -> List[str]:
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


class ProviderState:
    """Lazy-loaded model state."""

    def __init__(
        self,
        model_id: str,
        model_name: str,
        default_max_new_tokens: int,
        max_new_tokens_cap: int,
    ) -> None:
        self.model_id = model_id
        self.model_name = model_name
        self.default_max_new_tokens = max(1, int(default_max_new_tokens))
        self.max_new_tokens_cap = max(self.default_max_new_tokens, int(max_new_tokens_cap))
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
        hit_token_limit = completion_tokens >= int(max_new_tokens)
        return {
            "text": output_text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "hit_token_limit": hit_token_limit,
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
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", ""))
            if item_type in {"text", "input_text", "output_text"}:
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
                    continue
                if isinstance(value, dict):
                    nested = value.get("value") or value.get("text")
                    if isinstance(nested, str):
                        parts.append(nested)
                        continue
            for key in ("text", "value", "content"):
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
                    break
        return "\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "value", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
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
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        start_ts = time.time()
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            LOGGER.info("GET %s -> 200 (%.1fms)", self.path, (time.time() - start_ts) * 1000)
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
            LOGGER.info("GET %s -> 200 (%.1fms)", self.path, (time.time() - start_ts) * 1000)
            return

        _json_response(self, 404, {"error": "not found"})
        LOGGER.warning("GET %s -> 404 (%.1fms)", self.path, (time.time() - start_ts) * 1000)

    def do_POST(self) -> None:
        req_start_ts = time.time()
        if self.path not in {"/v1/chat/completions", "/v1/responses"}:
            _json_response(self, 404, {"error": "not found"})
            LOGGER.warning("POST %s -> 404 (%.1fms)", self.path, (time.time() - req_start_ts) * 1000)
            return

        content_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            LOGGER.warning("POST %s -> 400 invalid json (%.1fms)", self.path, (time.time() - req_start_ts) * 1000)
            return

        temperature = float(payload.get("temperature", 0.0))
        requested_max_tokens = (
            payload.get("max_tokens")
            or payload.get("max_new_tokens")
            or payload.get("max_output_tokens")
            or payload.get("max_completion_tokens")
            or self.state.default_max_new_tokens
        )
        max_new_tokens = min(max(1, int(requested_max_tokens)), self.state.max_new_tokens_cap)
        cap_hit = int(requested_max_tokens) > int(max_new_tokens)
        stream = bool(payload.get("stream", False))

        if self.path == "/v1/responses":
            messages = _normalize_responses_input(payload.get("input", []))
        else:
            messages = _normalize_messages(payload.get("messages", []))

        try:
            infer_start_ts = time.time()
            output = self.state.generate_chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
            )
            infer_ms = (time.time() - infer_start_ts) * 1000
        except Exception as error:
            _json_response(self, 500, {"error": str(error)})
            LOGGER.exception("POST %s -> 500 model error", self.path)
            return

        model_name = str(payload.get("model") or self.state.model_name)

        if stream and self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            role_chunk = {
                "id": "chatcmpl-local-001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(role_chunk, ensure_ascii=False)}\\n\\n".encode("utf-8"))
            self.wfile.flush()

            for piece in _split_text_chunks(output["text"]):
                chunk = {
                    "id": "chatcmpl-local-001",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\\n\\n".encode("utf-8"))
                self.wfile.flush()

            done_chunk = {
                "id": "chatcmpl-local-001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "length" if output.get("hit_token_limit") else "stop",
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(done_chunk, ensure_ascii=False)}\\n\\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\\n\\n")
            self.wfile.flush()
            LOGGER.info(
                "POST %s stream -> 200 prompt=%s completion=%s requested=%s applied=%s cap_hit=%s infer=%.1fms total=%.1fms",
                self.path,
                output["prompt_tokens"],
                output["completion_tokens"],
                requested_max_tokens,
                max_new_tokens,
                cap_hit,
                infer_ms,
                (time.time() - req_start_ts) * 1000,
            )
            return

        if stream and self.path == "/v1/responses":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            for piece in _split_text_chunks(output["text"]):
                event = {"type": "response.output_text.delta", "delta": piece}
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\\n\\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: {\"type\":\"response.completed\"}\\n\\n")
            self.wfile.write(b"data: [DONE]\\n\\n")
            self.wfile.flush()
            LOGGER.info(
                "POST %s stream -> 200 prompt=%s completion=%s requested=%s applied=%s cap_hit=%s infer=%.1fms total=%.1fms",
                self.path,
                output["prompt_tokens"],
                output["completion_tokens"],
                requested_max_tokens,
                max_new_tokens,
                cap_hit,
                infer_ms,
                (time.time() - req_start_ts) * 1000,
            )
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
            LOGGER.info(
                "POST %s -> 200 prompt=%s completion=%s infer=%.1fms total=%.1fms",
                self.path,
                output["prompt_tokens"],
                output["completion_tokens"],
                infer_ms,
                (time.time() - req_start_ts) * 1000,
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
                        "finish_reason": "length" if output.get("hit_token_limit") else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": output["prompt_tokens"],
                    "completion_tokens": output["completion_tokens"],
                    "total_tokens": output["total_tokens"],
                },
            },
        )
        LOGGER.info(
            "POST %s -> 200 prompt=%s completion=%s requested=%s applied=%s cap_hit=%s infer=%.1fms total=%.1fms",
            self.path,
            output["prompt_tokens"],
            output["completion_tokens"],
            requested_max_tokens,
            max_new_tokens,
            cap_hit,
            infer_ms,
            (time.time() - req_start_ts) * 1000,
        )


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenAI-compatible OpenVINO local provider")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--model-id", required=True, help="HuggingFace id or local model directory")
    parser.add_argument("--model-name", default=None, help="Model name returned by /v1/models")
    parser.add_argument("--eager-load", action="store_true", help="Load model at startup")
    parser.add_argument(
        "--default-max-new-tokens",
        type=int,
        default=16,
        help="Default max_new_tokens when request does not specify token limits",
    )
    parser.add_argument(
        "--max-new-tokens-cap",
        type=int,
        default=32,
        help="Hard cap for requested max_new_tokens to avoid long-running generations",
    )
    parser.add_argument("--log-level", default="INFO", help="Python logging level (DEBUG/INFO/WARN/ERROR)")
    return parser.parse_args()


def main() -> None:
    args = _build_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    model_name = args.model_name or args.model_id
    ProviderHandler.state = ProviderState(
        model_id=args.model_id,
        model_name=model_name,
        default_max_new_tokens=args.default_max_new_tokens,
        max_new_tokens_cap=args.max_new_tokens_cap,
    )
    if args.eager_load:
        ProviderHandler.state.ensure_loaded()

    server = ThreadingHTTPServer((args.host, args.port), ProviderHandler)
    print(f"Local OpenVINO provider running at http://{args.host}:{args.port} (model={model_name})")
    server.serve_forever()


if __name__ == "__main__":
    main()

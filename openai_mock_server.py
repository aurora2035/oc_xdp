"""OpenAI-compatible mock model server for OpenClaw runtime integration.

This server is used as a local stub model provider in development:
- Supports /v1/models
- Supports /v1/chat/completions (sync + SSE stream)
- Supports /v1/responses (sync + SSE stream)

Design goal:
- Keep behavior deterministic and lightweight
- Provide intent-aware hinting for xdp-agent-bridge skill usage
- Offer basic tool-call shaped outputs when tools are provided
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    """Write a JSON HTTP response with UTF-8 encoding."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _extract_user_text(messages: List[Dict[str, Any]]) -> str:
    """Extract the latest user text from OpenAI-style message payloads."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                chunks = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        chunks.append(str(item.get("text", "")))
                return "\n".join(chunks)
    return ""


def _extract_user_text_from_responses_input(input_obj: Any) -> str:
    """Extract user text from /v1/responses input schema.

Compatible with common shapes:
1) input: [{role, content:[{type:text, text:...}]}]
2) input: "plain text"
"""
    if isinstance(input_obj, str):
        return input_obj
    if isinstance(input_obj, list):
        normalized_messages: List[Dict[str, Any]] = []
        for item in input_obj:
            if isinstance(item, dict):
                normalized_messages.append(item)
        return _extract_user_text(normalized_messages)
    return ""


def _build_response_text(user_text: str) -> str:
    """Generate deterministic mock response text based on lightweight intent rules."""
    if any(token in user_text for token in ["痘", "acne", "精华", "推荐", "护肤"]):
        return (
            "[mock-nlu-planner] 检测到护肤导购意图(product_qa)。"
            "请调用 xdp-agent-bridge skill，把用户原文转发给本地 bridge 并返回 text 字段。"
        )
    return "[mock-nlu-planner] 普通咨询。可直接简短回答，必要时调用 xdp-agent-bridge。"


def _pick_tool_name(payload: Dict[str, Any]) -> str | None:
    """Pick a tool name from OpenAI tools if present.

This is best-effort compatibility: OpenClaw may or may not rely on tool-calls
for this provider path, but returning a valid shape improves interoperability.
"""
    tools = payload.get("tools", [])
    if not isinstance(tools, list):
        return None
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict):
            name = tool["function"].get("name")
            if isinstance(name, str) and name:
                return name
    return None


class MockHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing OpenAI-compatible mock endpoints."""

    server_version = "OpenAIMock/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        """Keep output concise in terminal by disabling default access logs."""
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
                    "data": [{"id": "stub-planner-nlu", "object": "model", "owned_by": "local"}],
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
        payload = json.loads(raw.decode("utf-8"))
        if self.path == "/v1/responses":
            user_text = _extract_user_text_from_responses_input(payload.get("input", []))
        else:
            user_text = _extract_user_text(payload.get("messages", []))

        response_text = _build_response_text(user_text)

        stream = bool(payload.get("stream", False))
        model = payload.get("model", "stub-planner-nlu")
        tool_name = _pick_tool_name(payload)

        if stream and self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            if tool_name and "导购" in response_text:
                chunk = {
                    "id": "chatcmpl-mock-001",
                    "object": "chat.completion.chunk",
                    "created": 1730000000,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "id": "call_xdp_bridge_1",
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps({"text": user_text}, ensure_ascii=False),
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            else:
                chunk = {
                    "id": "chatcmpl-mock-001",
                    "object": "chat.completion.chunk",
                    "created": 1730000000,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": response_text}, "finish_reason": None}],
                }
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))

            done_chunk = {
                "id": "chatcmpl-mock-001",
                "object": "chat.completion.chunk",
                "created": 1730000000,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(done_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            return

        if stream and self.path == "/v1/responses":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            event = {
                "type": "response.output_text.delta",
                "delta": response_text,
            }
            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: {\"type\":\"response.completed\"}\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return

        if self.path == "/v1/responses":
            _json_response(
                self,
                200,
                {
                    "id": "resp-mock-001",
                    "object": "response",
                    "model": model,
                    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": response_text}]}],
                    "status": "completed",
                },
            )
            return

        _json_response(
            self,
            200,
            {
                "id": "chatcmpl-mock-001",
                "object": "chat.completion",
                "created": 1730000000,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": (
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_xdp_bridge_1",
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps({"text": user_text}, ensure_ascii=False),
                                        },
                                    }
                                ],
                            }
                            if (tool_name and "导购" in response_text)
                            else {"role": "assistant", "content": response_text}
                        ),
                        "finish_reason": "tool_calls" if (tool_name and "导购" in response_text) else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 32, "completion_tokens": 28, "total_tokens": 60},
            },
        )


def _build_args() -> argparse.Namespace:
    """Parse CLI args for host/port."""
    parser = argparse.ArgumentParser(description="OpenAI-compatible mock server for OpenClaw")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    return parser.parse_args()


def main() -> None:
    """Start threaded mock HTTP server."""
    args = _build_args()
    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"Mock OpenAI server running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

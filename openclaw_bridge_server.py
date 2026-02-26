"""Bridge HTTP service between OpenClaw runtime and Python Agent core.

Responsibilities:
- Expose a stable local API for OpenClaw skill scripts
- Convert request payload into AgentInput
- Return structured JSON output (text + nlu + plan + skill outputs)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from agent import AgentInput, OpenClawAgent
from agent.config import load_agent_config


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    """Write JSON response to the HTTP client."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _decode_audio_from_payload(payload: Dict[str, Any]) -> bytes | None:
    """Decode audio bytes from payload.

    Supported formats:
    - `audio`: base64 string (preferred)
    - `audio`: data URL string with base64 segment
    - `audio`: list[int] byte array
    - `audio_b64`: base64 string (backward compatible)
    """
    audio_value = payload.get("audio")

    if isinstance(audio_value, list) and audio_value:
        if all(isinstance(item, int) and 0 <= item <= 255 for item in audio_value):
            return bytes(audio_value)
        raise ValueError("invalid audio byte array")

    encoded: Any = audio_value
    if not (isinstance(encoded, str) and encoded):
        encoded = payload.get("audio_b64")

    if isinstance(encoded, str) and encoded:
        base64_value = encoded
        if "," in encoded and encoded.strip().lower().startswith("data:audio"):
            base64_value = encoded.split(",", 1)[1]
        try:
            return base64.b64decode(base64_value)
        except Exception as error:
            raise ValueError("invalid audio base64 payload") from error

    return None


class BridgeHandler(BaseHTTPRequestHandler):
    """Request handler for bridge endpoints.

    Endpoints:
    - GET /health
    - POST /v1/assist
    """

    agent: OpenClawAgent

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default access log noise for cleaner CLI output."""
        return

    def do_GET(self) -> None:
        """Health check endpoint."""
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        """Main inference endpoint used by OpenClaw skill script."""
        if self.path != "/v1/assist":
            _json_response(self, 404, {"error": "not found"})
            return

        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len <= 0:
            _json_response(self, 400, {"error": "empty body"})
            return

        raw = self.rfile.read(content_len)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        text = payload.get("text")
        response_mode = payload.get("response_mode") or "text"
        upstream_nlu = payload.get("nlu")
        upstream_plan = payload.get("plan")
        try:
            audio_data = _decode_audio_from_payload(payload)
        except ValueError as error:
            _json_response(self, 400, {"error": str(error)})
            return

        try:
            output = self.agent.process_sync(
                AgentInput(
                    text=text,
                    audio=audio_data,
                    response_mode=str(response_mode),
                    upstream_nlu=upstream_nlu if isinstance(upstream_nlu, dict) else None,
                    upstream_plan=upstream_plan if isinstance(upstream_plan, list) else None,
                )
            )
            _json_response(
                self,
                200,
                {
                    "text": output.text,
                    "audio_b64": output.audio_b64,
                    "nlu": output.nlu,
                    "plan": output.plan,
                    "skill_outputs": output.skill_outputs,
                },
            )
        except Exception as error:
            _json_response(self, 500, {"error": str(error)})


def _build_args() -> argparse.Namespace:
    """Parse CLI options."""
    parser = argparse.ArgumentParser(description="OpenClaw <-> Agent bridge server")
    parser.add_argument("--config", default="config/agent.yaml", help="Agent config path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8099, help="Bind port")
    return parser.parse_args()


def main() -> None:
    """Bootstrap bridge service and block on serve_forever()."""
    args = _build_args()
    config = load_agent_config(Path(args.config))
    log_level = str(config.get("agent", {}).get("log_level", "INFO"))
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    BridgeHandler.agent = OpenClawAgent(config=config)
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    logging.info("Bridge server listening on http://%s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""OpenClaw skill helper script.

This script forwards user text to local Agent bridge endpoint and prints
raw JSON output for OpenClaw runtime to consume.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call local xDP Agent bridge")
    parser.add_argument("--text", default=None, help="User query text")
    parser.add_argument("--audio-input", default=None, help="Audio file path to send as `audio` base64")
    parser.add_argument(
        "--response-mode",
        default="text",
        choices=["text", "audio"],
        help="Response mode expected from bridge",
    )
    parser.add_argument(
        "--plan-json",
        default=None,
        help="Upstream plan JSON array to forward (used with strict_upstream_plan=true)",
    )
    parser.add_argument(
        "--nlu-json",
        default=None,
        help="Optional upstream NLU JSON object to forward",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8099/v1/assist", help="Bridge URL")
    return parser.parse_args()


def _parse_json_arg(raw: str, arg_name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid {arg_name}: expected valid JSON") from error


def main() -> None:
    args = _build_args()

    if not args.text and not args.audio_input:
        raise SystemExit("Either --text or --audio-input is required")

    request_body: dict[str, str] = {
        "response_mode": args.response_mode,
    }

    if args.text is not None:
        request_body["text"] = args.text

    if args.audio_input:
        audio_path = Path(args.audio_input)
        if not audio_path.exists() or not audio_path.is_file():
            raise SystemExit(f"Audio file not found: {audio_path}")
        request_body["audio"] = base64.b64encode(audio_path.read_bytes()).decode("utf-8")

    if isinstance(args.plan_json, str) and args.plan_json.strip():
        parsed_plan = _parse_json_arg(args.plan_json, "--plan-json")
        if not isinstance(parsed_plan, list):
            raise SystemExit("Invalid --plan-json: expected JSON array")
        request_body["plan"] = parsed_plan

    if isinstance(args.nlu_json, str) and args.nlu_json.strip():
        parsed_nlu = _parse_json_arg(args.nlu_json, "--nlu-json")
        if not isinstance(parsed_nlu, dict):
            raise SystemExit("Invalid --nlu-json: expected JSON object")
        request_body["nlu"] = parsed_nlu

    payload = json.dumps(
        request_body,
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        args.url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            print(body)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        print(json.dumps({"error": f"http {error.code}", "detail": detail}, ensure_ascii=False))
        raise SystemExit(1)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

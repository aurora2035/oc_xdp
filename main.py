"""CLI entry for direct Agent invocation.

Used for:
- local functional testing
- text/audio path verification without OpenClaw runtime
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from agent import AgentInput, OpenClawAgent
from agent.config import load_agent_config


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw Shopping Agent MVP")
    parser.add_argument("--config", default="config/agent.yaml", help="Agent config path")
    parser.add_argument("--text", default=None, help="Text input")
    parser.add_argument("--response-mode", default="text", choices=["text", "audio"], help="Agent response mode")
    parser.add_argument("--audio-input", default=None, help="Audio file path for ASR")
    return parser.parse_args()


def main() -> None:
    args = _build_args()
    config = load_agent_config(args.config)

    log_level = str(config.get("agent", {}).get("log_level", "INFO"))
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    agent = OpenClawAgent(config)
    output = agent.process_sync(
        AgentInput(text=args.text, audio_input=args.audio_input, response_mode=args.response_mode)
    )
    print(
        json.dumps(
            {
                "text": output.text,
                "audio_b64": output.audio_b64,
                "nlu": output.nlu,
                "plan": output.plan,
                "skill_outputs": output.skill_outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

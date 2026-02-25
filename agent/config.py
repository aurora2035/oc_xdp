"""Configuration loader for Agent project.

Supports YAML (when PyYAML is installed) and JSON fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_agent_config(config_path: str | Path) -> Dict[str, Any]:
    """Load and validate top-level config mapping from path."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Agent config not found: {path}")

    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as file:
            payload = yaml.safe_load(file)
            if not isinstance(payload, dict):
                raise ValueError("Agent config must be a JSON/YAML object")
            return payload
    except ModuleNotFoundError:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("Agent config must be a JSON/YAML object")
            return payload

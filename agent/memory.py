"""Persistent memory module.

Stores:
- dialog history (capped)
- user profile
- recent product records (capped)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class AgentMemory:
    """In-memory model + JSON persistence for agent memory state."""

    memory_file: Path
    max_history_rounds: int = 3
    max_product_records: int = 5
    dialog_history: List[Dict[str, Any]] = field(default_factory=list)
    user_profile: Dict[str, Any] = field(
        default_factory=lambda: {
            "skin_type": None,
            "concerns": [],
            "age_range": None,
            "price_pref": None,
        }
    )
    product_records: List[str] = field(default_factory=list)

    def load(self) -> None:
        """Load persisted memory from JSON file if exists."""
        if not self.memory_file.exists():
            return
        payload = json.loads(self.memory_file.read_text(encoding="utf-8"))
        self.dialog_history = payload.get("dialog_history", [])
        self.user_profile = payload.get("user_profile", self.user_profile)
        self.product_records = payload.get("product_records", [])

    def save(self) -> None:
        """Persist current memory state into JSON file."""
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dialog_history": self.dialog_history,
            "user_profile": self.user_profile,
            "product_records": self.product_records,
        }
        self.memory_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_dialog(self, role: str, content: str) -> None:
        """Append one dialog item and enforce history cap."""
        self.dialog_history.append({"role": role, "content": content, "timestamp": _now_iso()})
        cap = self.max_history_rounds * 2
        if len(self.dialog_history) > cap:
            self.dialog_history = self.dialog_history[-cap:]

    def add_product_records(self, product_ids: List[str]) -> None:
        """Merge product ids while preserving recency and cap."""
        for product_id in product_ids:
            if product_id in self.product_records:
                self.product_records.remove(product_id)
            self.product_records.append(product_id)
        if len(self.product_records) > self.max_product_records:
            self.product_records = self.product_records[-self.max_product_records:]

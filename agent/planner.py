"""Planner module.

Transforms NLU output into an ordered executable skill plan.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class Planner:
    """Simple rule planner for MVP."""

    def build_plan(self, nlu: Dict[str, Any], query: str, cv_result: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        """Generate ordered skill list with params and async flags."""
        intent = nlu.get("intent", "chitchat")
        entities = nlu.get("entities", {})
        chain = nlu.get("skill_chain", [])

        plan: List[Dict[str, Any]] = []
        if "rag" in chain:
            plan.append(
                {
                    "skill_name": "rag",
                    "params": {"query": query, "entities": entities, "top_k": 3},
                    "async": False,
                }
            )

        gen_entities = dict(entities)
        if intent == "skin_analysis" and cv_result is None:
            gen_entities["cv_missing"] = True

        plan.append(
            {
                "skill_name": "generation",
                "params": {
                    "query": query,
                    "intent": intent,
                    "entities": gen_entities,
                    "rag_candidates": [],
                },
                "async": False,
            }
        )
        logger.info("Plan=%s", [item["skill_name"] for item in plan])
        return plan

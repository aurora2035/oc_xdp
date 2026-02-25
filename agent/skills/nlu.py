"""NLU skill.

Current implementation is an MVP stub:
- lightweight intent/entity extraction rules
- output schema aligned with planned model interface
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .base import BaseSkill, SkillParameter

logger = logging.getLogger(__name__)


class NLUSkill(BaseSkill):
    """Intent recognition and entity extraction skill."""

    name = "nlu"
    description = "Intent and entities by Qwen2.5-0.5B-Instruct profile."
    parameters = [
        SkillParameter("query", str, required=True),
        SkillParameter("cv_result", dict, required=False, default=None),
    ]

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params["query"].strip()
        cv_result = params.get("cv_result")
        lower = query.lower()

        intent = "chitchat"
        confidence = 0.72
        entities: Dict[str, Any] = {}
        skill_chain = ["generation"]

        if any(token in lower for token in ["痘", "acne", "精华", "推荐", "护肤"]):
            intent = "product_qa"
            confidence = 0.89
            skill_chain = ["rag", "generation"]
            if "痘" in lower or "acne" in lower:
                entities["concern"] = "acne"
            if "精华" in lower:
                entities["product_type"] = "serum"

        if any(token in lower for token in ["肤质", "皮肤", "出油", "敏感"]):
            intent = "skin_analysis"
            confidence = 0.86
            entities["analysis_required"] = True
            skill_chain = ["generation"] if cv_result is None else ["rag", "generation"]

        if any(token in lower for token in ["人工", "客服", "投诉", "转接"]):
            intent = "escalation"
            confidence = 0.95
            skill_chain = ["generation"]

        logger.info("NLU completed with intent=%s", intent)
        return {
            "intent": intent,
            "entities": entities,
            "skill_chain": skill_chain,
            "confidence": confidence,
            "model": {
                "name": "Qwen2.5-0.5B-Instruct",
                "optimization": "ipex-llm-int8-amx",
            },
            "cv_available": cv_result is not None,
        }

"""Generation skill.

Current implementation is a controllable template stub.
It will be replaced by real <=1B local model inference later.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .base import BaseSkill, SkillParameter

logger = logging.getLogger(__name__)


class GenerationSkill(BaseSkill):
    """Compose final assistant response from intent/entities/retrieval context."""

    name = "generation"
    description = "Generate response by local <=1B model profile."
    parameters = [
        SkillParameter("query", str, required=True),
        SkillParameter("intent", str, required=True),
        SkillParameter("entities", dict, required=False, default={}),
        SkillParameter("rag_candidates", list, required=False, default=[]),
    ]

    def _compose_product_text(self, query: str, rag_candidates: List[Dict[str, Any]]) -> str:
        if not rag_candidates:
            return f"你提到“{query}”，建议先选温和控油精华并建立耐受，再观察皮肤状态。"
        top_item = rag_candidates[0]
        return (
            f"宝子你这个问题问得太对了！你可以优先看“{top_item['title']}”，"
            f"因为它{top_item['desc']}，先隔天晚间少量使用更稳妥。"
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        intent = params["intent"]
        query = params["query"]
        rag_candidates = params.get("rag_candidates", [])

        if intent == "product_qa":
            text = self._compose_product_text(query, rag_candidates)
        elif intent == "skin_analysis":
            text = "你可以先做温和清洁+修护保湿+日间防晒；若后续补充图片我能给更精细建议。"
        elif intent == "escalation":
            text = "已为你标记人工客服优先接入，我先同步关键信息。"
        else:
            text = "收到，我可以继续帮你做护肤和产品推荐。"

        logger.info("Generation completed")
        return {
            "text": text,
            "style": "livestream-guide",
            "entities_used": params.get("entities", {}),
            "model": {
                "name": "Qwen2.5-0.5B-Instruct",
                "optimization": "ipex-llm-int8-amx",
            },
        }

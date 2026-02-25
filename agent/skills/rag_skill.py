"""RAG skill.

Uses xDP embedding when available, otherwise local fallback embedding,
then performs local similarity ranking over product catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

from .base import BaseSkill, SkillParameter

logger = logging.getLogger(__name__)


def _fallback_embed(text: str, dim: int = 16) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    for index, char in enumerate(text):
        vector[index % dim] += (ord(char) % 97) / 97.0
    norm = np.linalg.norm(vector)
    return vector if norm == 0 else vector / norm


class RAGSkill(BaseSkill):
    """Retrieve relevant product candidates for downstream generation."""

    name = "rag"
    description = "RAG by xDP embedding + local FAISS-like retrieval."
    parameters = [
        SkillParameter("query", str, required=True),
        SkillParameter("entities", dict, required=False, default={}),
        SkillParameter("top_k", int, required=False, default=3),
    ]

    def __init__(self, embedding_config: Dict[str, Any] | None = None) -> None:
        super().__init__()
        self.embedding_config = embedding_config or {}
        self.catalog: List[Dict[str, Any]] = [
            {"product_id": "sku_1001", "title": "净痘修护精华", "desc": "含水杨酸与积雪草，适合油痘肌温和修护"},
            {"product_id": "sku_1002", "title": "舒缓维稳精华", "desc": "神经酰胺配方，帮助稳定敏感泛红"},
            {"product_id": "sku_1003", "title": "轻润保湿精华", "desc": "透明质酸补水，清爽不黏腻"},
            {"product_id": "sku_1004", "title": "焕亮VC精华", "desc": "维C衍生物，提亮肤色暗沉"},
        ]

    def _xdp_embedding(self, text: str) -> np.ndarray:
        try:
            from embedding.embedding import embedding as xdp_embedding  # type: ignore

            backend = self.embedding_config.get("backend", "transformers")
            tensor = xdp_embedding(backend=backend, texts=[text], overrides=self.embedding_config.get("overrides"))
            if tensor is None:
                raise RuntimeError("empty embedding result")
            array = np.asarray(tensor[0], dtype=np.float32)
            norm = np.linalg.norm(array)
            return array if norm == 0 else array / norm
        except Exception as error:
            logger.info("xdp embedding unavailable, using fallback embedding: %s", error)
            return _fallback_embed(text)

    def _retrieve(self, query_vector: np.ndarray, top_k: int) -> List[Dict[str, Any]]:
        matrix = np.vstack([self._xdp_embedding(f"{item['title']} {item['desc']}") for item in self.catalog])

        if matrix.shape[1] != query_vector.shape[0]:
            if matrix.shape[1] > query_vector.shape[0]:
                query_vector = np.pad(query_vector, (0, matrix.shape[1] - query_vector.shape[0]))
            else:
                matrix = np.pad(matrix, ((0, 0), (0, query_vector.shape[0] - matrix.shape[1])))

        scores = matrix @ query_vector
        top_indices = np.argsort(scores)[::-1][:top_k]
        results: List[Dict[str, Any]] = []
        for idx in top_indices:
            item = dict(self.catalog[int(idx)])
            item["score"] = float(scores[int(idx)])
            results.append(item)
        return results

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("RAG started")
        query_vector = self._xdp_embedding(params["query"])
        candidates = self._retrieve(query_vector=query_vector, top_k=params["top_k"])
        return {
            "query": params["query"],
            "top_k": params["top_k"],
            "candidates": candidates,
        }

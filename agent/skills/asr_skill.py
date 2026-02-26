"""ASR skill.

Behavior:
- Try xDP ASR API first
- Fallback to deterministic local decode strategy
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict

from .base import BaseSkill, SkillParameter

logger = logging.getLogger(__name__)


class ASRSkill(BaseSkill):
    """Audio-to-text skill with robust fallback path."""

    name = "asr"
    description = "ASR wrapper using xDP API interface with async execution and fallback."
    parameters = [
        SkillParameter("config", dict, required=True),
    ]

    def _fallback_asr(self, audio_data: bytes) -> Dict[str, Any]:
        if not audio_data:
            text = ""
        else:
            try:
                text = audio_data.decode("utf-8", errors="ignore").strip()
            except Exception:
                text = ""
        if not text:
            text = "[ASR_FALLBACK] 暂无法识别音频内容"
        return {
            "transcript": text,
            "confidence": 0.5,
            "duration_ms": 0,
            "fallback": True,
        }

    def _invoke_xdp(self, config: Dict[str, Any]) -> Dict[str, Any]:
        safe_config = dict(config)
        num_runs = safe_config.get("num_runs")
        if isinstance(num_runs, (int, float)):
            safe_config["num_runs"] = max(1, int(num_runs))
        elif num_runs is None:
            safe_config["num_runs"] = 1

        try:
            from xdp_api import get_xdp
            asr_fn = get_xdp("asr")
            result = asr_fn(safe_config)
            
            if isinstance(result, dict):
                transcript = (
                    result.get("transcript")
                    or result.get("transcription")
                    or result.get("text")
                    or ""
                )
                avg_inference_time = result.get("avg_inference_time")
                duration_ms = 0
                if isinstance(avg_inference_time, (int, float)):
                    duration_ms = int(avg_inference_time * 1000)
                return {
                    "transcript": transcript,
                    "confidence": float(result.get("confidence", 0.8)),
                    "duration_ms": int(result.get("duration_ms", duration_ms)),
                    "fallback": False,
                }
        except Exception as error:
            logger.info("xdp asr unavailable, using fallback: %s", error)
        
        return {"transcript": "[ASR_FALLBACK] 暂无法识别音频内容", "fallback": True}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("ASR started")
        result = await asyncio.to_thread(self._invoke_xdp, params["config"])
        logger.info("ASR completed")
        return result
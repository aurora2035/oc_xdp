"""TTS skill.

Behavior:
- Use unified xDP TTS API (`tts(config)`) with demo-compatible keys.
- Convert raw audio bytes to base64 so outputs remain JSON-serializable.
- Provide deterministic fallback payload when backend is unavailable.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict

from .base import BaseSkill, SkillParameter

logger = logging.getLogger(__name__)


class TTSSkill(BaseSkill):
    """Text-to-speech skill using xDP API with safe JSON output."""

    name = "tts"
    description = "TTS wrapper using xDP unified API with robust fallback behavior."
    parameters = [
        SkillParameter("text", str, required=True),
        SkillParameter("config", dict, required=True),
    ]

    def _fallback_tts(self, text: str, config: Dict[str, Any]) -> Dict[str, Any]:
        raw = (text or "").encode("utf-8")[:1024] or b"tts_fallback"
        return {
            "audio_b64": base64.b64encode(raw).decode("utf-8"),
            "audio_size": len(raw),
            "model": config.get("tts_model") or config.get("model_name") or "fallback_tts",
            "mode": config.get("tts_mode") or config.get("mode") or config.get("default_mode") or "zero_shot",
            "fallback": True,
        }

    def _invoke_xdp(self, text: str, config: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(config)
        merged.setdefault("text", text)
        merged.setdefault("input_data", text)

        try:
            from xdp_api import get_xdp  # type: ignore

            tts_fn = get_xdp("tts")
            result = tts_fn(merged)

            if isinstance(result, bytes):
                audio_bytes = result
                return {
                    "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
                    "audio_size": len(audio_bytes),
                    "model": merged.get("tts_model") or merged.get("model_name"),
                    "mode": merged.get("tts_mode") or merged.get("mode") or merged.get("default_mode") or "zero_shot",
                    "fallback": False,
                }

            if isinstance(result, dict):
                audio_obj = result.get("audio")
                if isinstance(audio_obj, (bytes, bytearray)):
                    audio_bytes = bytes(audio_obj)
                    return {
                        "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
                        "audio_size": len(audio_bytes),
                        "model": result.get("model") or merged.get("tts_model") or merged.get("model_name"),
                        "mode": merged.get("tts_mode") or merged.get("mode") or merged.get("default_mode") or "zero_shot",
                        "fallback": False,
                    }

                if isinstance(result.get("audio_b64"), str):
                    return {
                        "audio_b64": result["audio_b64"],
                        "audio_size": int(result.get("audio_size") or 0),
                        "model": result.get("model") or merged.get("tts_model") or merged.get("model_name"),
                        "mode": result.get("mode")
                        or merged.get("tts_mode")
                        or merged.get("mode")
                        or merged.get("default_mode")
                        or "zero_shot",
                        "fallback": bool(result.get("fallback", False)),
                    }

        except Exception as error:
            logger.info("xdp tts unavailable, using fallback: %s", error)

        return self._fallback_tts(text, merged)

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("TTS started")
        result = await asyncio.to_thread(self._invoke_xdp, params["text"], params["config"])
        logger.info("TTS completed")
        return result

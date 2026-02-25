"""Core orchestration module for OpenClaw shopping Agent.

Flow:
1. Normalize input (text/audio)
2. Optional ASR preprocessing for audio
3. Run NLU
4. Build plan
5. Execute skills
6. Persist memory and return output
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory import AgentMemory
from .planner import Planner
from .skills import ASRSkill, GenerationSkill, NLUSkill, RAGSkill, TTSSkill
from .skills.base import BaseSkill

logger = logging.getLogger(__name__)


@dataclass
class AgentInput:
    text: Optional[str] = None
    audio: Optional[bytes] = None
    audio_input: Optional[str] = None
    image: Optional[bytes] = None
    response_mode: str = "text"


@dataclass
class AgentOutput:
    text: str
    nlu: Dict[str, Any]
    plan: List[Dict[str, Any]]
    skill_outputs: Dict[str, Dict[str, Any]]
    audio_b64: Optional[str] = None


class OpenClawAgent:
    """Main orchestrator that owns skill registry, planner, and memory."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.skills: Dict[str, BaseSkill] = {}
        self.planner = Planner()

        memory_cfg = config.get("memory", {})
        self.memory = AgentMemory(
            memory_file=Path(memory_cfg.get("store_path", "./data/agent_memory.json")),
            max_history_rounds=int(memory_cfg.get("max_history_rounds", 3)),
            max_product_records=int(memory_cfg.get("max_product_records", 5)),
        )
        self.memory.load()

        self.register_skill(ASRSkill())
        self.register_skill(NLUSkill())
        self.register_skill(RAGSkill(embedding_config=config.get("embedding", {})))
        self.register_skill(GenerationSkill())
        self.register_skill(TTSSkill())

    def register_skill(self, skill: BaseSkill) -> None:
        """Register one skill instance into runtime registry."""
        self.skills[skill.name] = skill
        logger.info("Skill registered: %s", skill.name)

    async def _run_skill(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run one skill with fallback-on-error behavior."""
        try:
            return await self.skills[name].run(params)
        except Exception as error:
            logger.info("Skill %s failed, fallback used: %s", name, error)
            return {"error": str(error), "fallback": True}

    async def _run_plan(self, plan: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Execute planner output sequentially for MVP."""
        outputs: Dict[str, Dict[str, Any]] = {}
        for step in plan:
            name = step["skill_name"]
            outputs[name] = await self._run_skill(name, step.get("params", {}))
        return outputs

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """Run one end-to-end request through the full pipeline."""
        query = (agent_input.text or "").strip()
        skill_outputs: Dict[str, Dict[str, Any]] = {}

        # 1. 音频 → ASR 转文字
        if not query and agent_input.audio_input is not None:
            asr_config = self.config.get("xdp", {}).get("asr", {}).copy()
            asr_config["input"] = agent_input.audio_input
            asr_output = await self._run_skill("asr", {"config": asr_config})
            skill_outputs["asr"] = asr_output
            query = (asr_output.get("transcript") or "").strip()

        if not query and agent_input.audio:
            asr_config = self.config.get("xdp", {}).get("asr", {}).copy()
            temp_audio_path: Optional[str] = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_file.write(agent_input.audio)
                    temp_audio_path = temp_file.name
                asr_config["input"] = temp_audio_path
                asr_output = await self._run_skill("asr", {"config": asr_config})
            finally:
                if temp_audio_path:
                    Path(temp_audio_path).unlink(missing_ok=True)

            transcript = (asr_output.get("transcript") or "").strip()
            if not transcript:
                transcript = agent_input.audio.decode("utf-8", errors="ignore").strip()
                asr_output = {
                    "transcript": transcript,
                    "confidence": 0.5,
                    "duration_ms": 0,
                    "fallback": True,
                }

            skill_outputs["asr"] = asr_output
            query = transcript

        if not query:
            raise ValueError("MVP requires text input or audio input with ASR transcript")

        self.memory.add_dialog("user", query)

        # 2. NLU 理解意图
        nlu = await self._run_skill("nlu", {"query": query, "cv_result": None})
         # 3. Planner 生成执行计划
        plan = self.planner.build_plan(nlu, query=query, cv_result=None)
        # 4. 按顺序执行 skill 链
        chain_outputs = await self._run_plan(plan)
        skill_outputs.update(chain_outputs)

        # 5. RAG → Generation 生成回答
        if "rag" in chain_outputs and "generation" in chain_outputs and "error" not in chain_outputs["generation"]:
            generation_params = dict(plan[-1]["params"])
            generation_params["rag_candidates"] = chain_outputs["rag"].get("candidates", [])
            skill_outputs["generation"] = await self._run_skill("generation", generation_params)

        final_text = skill_outputs.get("generation", {}).get("text")
        if not final_text:
            final_text = "抱歉，我暂时无法完成回答，请稍后重试。"

        audio_b64: Optional[str] = None
        # 6. Optional：生成 TTS 音频
        if (agent_input.response_mode or "text").strip().lower() == "audio":
            tts_output = await self._run_skill(
                "tts",
                {
                    "text": final_text,
                    "config": self.config.get("xdp", {}).get("tts", {}),
                },
            )
            skill_outputs["tts"] = tts_output
            if isinstance(tts_output, dict):
                audio_b64 = tts_output.get("audio_b64")

        product_ids = [
            item.get("product_id")
            for item in skill_outputs.get("rag", {}).get("candidates", [])
            if item.get("product_id")
        ]
        if product_ids:
            self.memory.add_product_records(product_ids)
        
        # 7. 存记忆
        self.memory.add_dialog("assistant", final_text)
        self.memory.save()

        return AgentOutput(
            text=final_text,
            nlu=nlu,
            plan=plan,
            skill_outputs=skill_outputs,
            audio_b64=audio_b64,
        )

    def process_sync(self, agent_input: AgentInput) -> AgentOutput:
        """Synchronous wrapper for CLI/tests."""
        return asyncio.run(self.process(agent_input))

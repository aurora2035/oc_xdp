"""NLU skill.

Supports:
- local Qwen inference via transformers
- OpenAI-compatible chat completion inference
- rule-based fallback when model is unavailable or output is invalid
"""

from __future__ import annotations

import logging
import json
import os
from typing import Optional
from typing import Any, Dict
from urllib import request

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

    def __init__(self, nlu_config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.nlu_config = nlu_config or {}
        self.backend = str(self.nlu_config.get("backend", "transformers")).strip().lower()
        self.model_name = str(self.nlu_config.get("model", "Qwen2.5-0.5B-Instruct"))
        self.optimization = str(self.nlu_config.get("optimization", "ipex-llm-int8-amx"))
        self.temperature = float(self.nlu_config.get("temperature", 0.0))
        self.max_new_tokens = int(self.nlu_config.get("max_new_tokens", 256))

        self._tokenizer: Any = None
        self._model: Any = None
        self._openai_url = str(self.nlu_config.get("openai_base_url", "http://127.0.0.1:18080/v1")).rstrip("/")
        self._openai_model = str(self.nlu_config.get("openai_model", self.model_name))
        self._openai_api_key = str(self.nlu_config.get("openai_api_key", os.getenv("OPENAI_API_KEY", "stub-key")))

    def _fallback_rules(self, query: str, cv_result: Dict[str, Any] | None) -> Dict[str, Any]:
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

        logger.info("NLU fallback completed with intent=%s", intent)
        return {
            "intent": intent,
            "entities": entities,
            "skill_chain": skill_chain,
            "confidence": confidence,
            "model": {
                "name": self.model_name,
                "optimization": self.optimization,
                "backend": "rules-fallback",
            },
            "cv_available": cv_result is not None,
            "fallback": True,
        }

    def _build_prompt(self, query: str, cv_result: Dict[str, Any] | None) -> str:
        cv_available = cv_result is not None
        return (
            "你是电商护肤助手的NLU模块。请只输出一个JSON对象，不要输出任何额外文本。\n"
            "可选intent: product_qa, skin_analysis, escalation, chitchat。\n"
            "规则:\n"
            "1) product_qa: 用户在问推荐、成分、功效、产品选择。\n"
            "2) skin_analysis: 用户在问肤质分析、出油/敏感/状态诊断。\n"
            "3) escalation: 用户要求人工、投诉、转接客服。\n"
            "4) 其他归类为 chitchat。\n"
            "输出JSON结构:\n"
            "{\n"
            "  \"intent\": \"...\",\n"
            "  \"entities\": {\"concern\": \"...\", \"product_type\": \"...\", \"analysis_required\": true/false},\n"
            "  \"skill_chain\": [\"rag\", \"generation\"] 或 [\"generation\"],\n"
            "  \"confidence\": 0到1之间的小数\n"
            "}\n"
            f"输入query: {query}\n"
            f"cv_available: {str(cv_available).lower()}\n"
        )

    def _normalize_output(self, parsed: Dict[str, Any], cv_result: Dict[str, Any] | None) -> Dict[str, Any]:
        intent = str(parsed.get("intent", "chitchat"))
        if intent not in {"product_qa", "skin_analysis", "escalation", "chitchat"}:
            intent = "chitchat"

        entities = parsed.get("entities", {})
        if not isinstance(entities, dict):
            entities = {}

        chain = parsed.get("skill_chain", ["generation"])
        if not isinstance(chain, list) or not chain:
            chain = ["generation"]
        chain = [step for step in chain if step in {"rag", "generation"}]
        if not chain:
            chain = ["generation"]
        if "generation" not in chain:
            chain.append("generation")

        confidence_raw = parsed.get("confidence", 0.7)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))

        return {
            "intent": intent,
            "entities": entities,
            "skill_chain": chain,
            "confidence": confidence,
            "model": {
                "name": self.model_name,
                "optimization": self.optimization,
                "backend": self.backend,
            },
            "cv_available": cv_result is not None,
            "fallback": False,
        }

    def _extract_json(self, text: str) -> Dict[str, Any]:
        raw = text.strip()
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                data, _ = decoder.raw_decode(raw, index)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        raise ValueError("No JSON object found in model output")

    def _run_openai_compatible(self, prompt: str) -> Dict[str, Any]:
        url = f"{self._openai_url}/chat/completions"
        payload = {
            "model": self._openai_model,
            "messages": [
                {"role": "system", "content": "你是一个严格输出JSON的NLU引擎。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._openai_api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=20) as response:  # nosec B310
            result = json.loads(response.read().decode("utf-8"))

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not isinstance(content, str):
            raise ValueError("Invalid content type from OpenAI-compatible response")
        return self._extract_json(content)

    def _run_transformers(self, prompt: str) -> Dict[str, Any]:
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as error:
            raise RuntimeError(f"transformers not available: {error}") from error

        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            self._model.eval()

        messages = [
            {"role": "system", "content": "你是一个严格输出JSON的NLU引擎。"},
            {"role": "user", "content": prompt},
        ]
        rendered = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self._tokenizer([rendered], return_tensors="pt")
        with torch.no_grad():
            generated = self._model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                do_sample=self.temperature > 0,
            )
        generated_ids = generated[:, model_inputs["input_ids"].shape[1] :]
        text = self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return self._extract_json(text)

    def _run_openvino(self, prompt: str) -> Dict[str, Any]:
        try:
            from optimum.intel.openvino import OVModelForCausalLM  # type: ignore
            from transformers import AutoTokenizer  # type: ignore
        except Exception as error:
            raise RuntimeError(f"openvino/optimum not available: {error}") from error

        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            self._model = OVModelForCausalLM.from_pretrained(self.model_name, trust_remote_code=True)

        messages = [
            {"role": "system", "content": "你是一个严格输出JSON的NLU引擎。"},
            {"role": "user", "content": prompt},
        ]
        rendered = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self._tokenizer([rendered], return_tensors="pt")

        generated = self._model.generate(
            **model_inputs,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            do_sample=self.temperature > 0,
        )
        generated_ids = generated[:, model_inputs["input_ids"].shape[1] :]
        text = self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return self._extract_json(text)

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params["query"].strip()
        cv_result = params.get("cv_result")
        prompt = self._build_prompt(query, cv_result)

        try:
            if self.backend == "openai_compatible":
                parsed = self._run_openai_compatible(prompt)
            elif self.backend == "openvino":
                parsed = self._run_openvino(prompt)
            else:
                parsed = self._run_transformers(prompt)
            result = self._normalize_output(parsed, cv_result)
            logger.info("NLU model completed with intent=%s", result["intent"])
            return result
        except Exception as error:
            logger.info("NLU model unavailable, fallback used: %s", error)
            return self._fallback_rules(query=query, cv_result=cv_result)

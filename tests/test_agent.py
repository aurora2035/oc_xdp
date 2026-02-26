from __future__ import annotations

from pathlib import Path

from agent import AgentInput, OpenClawAgent


def _build_config(tmp_path: Path) -> dict:
    return {
        "agent": {"name": "test-agent", "log_level": "INFO"},
        "orchestration": {
            "use_upstream_planner": False,
            "strict_upstream_plan": False,
        },
        "memory": {
            "store_path": str(tmp_path / "memory.json"),
            "max_history_rounds": 3,
            "max_product_records": 5,
        },
        "embedding": {
            "backend": "transformers",
            "overrides": {"model": "bge-m3"},
        },
        "xdp": {
            "asr": {
                "model": "funasr_nano",
                "language": "zh",
                "optimization": "amx_int8",
                "streaming": True,
            },
            "tts": {
                "tts_model": "cosyvoice2_0.5b",
                "tts_mode": "zero_shot",
            },
        },
    }


def test_text_path(tmp_path: Path) -> None:
    agent = OpenClawAgent(config=_build_config(tmp_path))
    output = agent.process_sync(AgentInput(text="我长痘了，推荐个精华"))
    assert output.nlu["intent"] == "product_qa"
    assert output.text
    assert output.plan[0]["skill_name"] == "rag"


def test_audio_asr_path(tmp_path: Path) -> None:
    agent = OpenClawAgent(config=_build_config(tmp_path))
    output = agent.process_sync(AgentInput(audio="我长痘了，推荐个精华".encode("utf-8")))
    assert "asr" in output.skill_outputs
    assert output.skill_outputs["asr"].get("transcript")
    assert output.text


def test_memory_limits(tmp_path: Path) -> None:
    agent = OpenClawAgent(config=_build_config(tmp_path))
    for i in range(6):
        agent.process_sync(AgentInput(text=f"第{i}轮测试，推荐精华"))
    assert len(agent.memory.dialog_history) <= 6
    assert len(agent.memory.product_records) <= 5


def test_audio_response_mode_uses_tts(tmp_path: Path) -> None:
    agent = OpenClawAgent(config=_build_config(tmp_path))
    output = agent.process_sync(AgentInput(text="给我推荐一款温和面霜", response_mode="audio"))
    assert output.text
    assert output.audio_b64
    assert "tts" in output.skill_outputs


def test_upstream_plan_is_reused(tmp_path: Path) -> None:
    agent = OpenClawAgent(config=_build_config(tmp_path))
    output = agent.process_sync(
        AgentInput(
            text="这条文案不应该触发本地nlu",
            upstream_nlu={
                "intent": "chitchat",
                "entities": {},
                "skill_chain": ["generation"],
                "confidence": 0.99,
                "model": {"name": "openclaw-upstream"},
                "cv_available": False,
            },
            upstream_plan=[
                {
                    "skill_name": "generation",
                    "params": {
                        "query": "来自openclaw的已规划query",
                        "intent": "chitchat",
                        "entities": {},
                        "rag_candidates": [],
                    },
                    "async": False,
                }
            ],
        )
    )
    assert output.nlu.get("model", {}).get("name") == "openclaw-upstream"
    assert len(output.plan) == 1
    assert output.plan[0]["skill_name"] == "generation"


def test_strict_upstream_mode_requires_plan(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    config["orchestration"] = {"use_upstream_planner": True, "strict_upstream_plan": True}
    agent = OpenClawAgent(config=config)
    try:
        agent.process_sync(AgentInput(text="hello"))
        assert False, "expected ValueError when strict upstream mode has no plan"
    except ValueError as error:
        assert "upstream plan required" in str(error)


def test_strict_upstream_mode_executes_plan(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    config["orchestration"] = {"use_upstream_planner": True, "strict_upstream_plan": True}
    agent = OpenClawAgent(config=config)
    output = agent.process_sync(
        AgentInput(
            text="hello",
            upstream_plan=[
                {
                    "skill_name": "generation",
                    "params": {
                        "query": "hello",
                        "intent": "chitchat",
                        "entities": {},
                        "rag_candidates": [],
                    },
                    "async": False,
                }
            ],
        )
    )
    assert output.plan[0]["skill_name"] == "generation"

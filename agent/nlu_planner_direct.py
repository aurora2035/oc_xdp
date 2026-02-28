"""
直接调用本地模型做 NLU/Planner
绕过 OpenClaw Agent 循环，单次调用 < 15s

使用方式:
    from agent.nlu_planner_direct import get_nlu_and_plan
    
    result = get_nlu_and_plan("我长痘了，推荐个精华")
    print(result)
    # {
    #   "intent": "product_qa",
    #   "entities": {"concern": "acne", "product_type": "serum"},
    #   "plan": [{"skill_name": "rag", ...}, {"skill_name": "generation", ...}]
    # }
"""

import json
import requests
from typing import Dict, Any, Optional

# 默认使用 mock server 或本地模型
DEFAULT_MODEL_URL = "http://127.0.0.1:18080/v1/chat/completions"
DEFAULT_MODEL_NAME = "qwen2-0.5b-ov"


def get_nlu_and_plan(
    text: str,
    model_url: str = DEFAULT_MODEL_URL,
    model_name: str = DEFAULT_MODEL_NAME,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    直接调用本地模型做 NLU 和 Planner
    
    Args:
        text: 用户输入文本
        model_url: 模型服务地址
        model_name: 模型名称
        timeout: 请求超时时间（秒）
    
    Returns:
        {
            "intent": str,
            "entities": dict,
            "plan": list,
            "confidence": float
        }
    
    Raises:
        requests.Timeout: 模型调用超时
        json.JSONDecodeError: 返回结果不是有效 JSON
    """
    
    # 构造 NLU/Planner prompt
    system_prompt = """你是智能导购助手的 NLU/Planner 模块。
你的任务是分析用户输入，提取意图、实体，并生成执行计划。

输出要求：
1. intent: 意图名称，必须是以下之一
   - product_qa: 商品咨询
   - skin_analysis: 肤质分析
   - usage_guide: 使用指导
   - general_chat: 闲聊

2. entities: 提取的关键实体
   - concern: 用户关注点（如痘痘、敏感、干燥等）
   - product_type: 产品类型（如精华、面霜、面膜等）
   - skin_type: 肤质（如油皮、干皮、敏感肌等）

3. plan: 执行计划，按顺序列出需要调用的 skill
   - rag: 商品检索
   - generation: 话术生成
   - skin_analysis: 肤质分析

4. confidence: 置信度（0-1）

只输出 JSON 格式，不要任何其他文字。"""

    user_prompt = f"""用户输入: {text}

请分析并输出 JSON:"""

    # 调用模型
    response = requests.post(
        model_url,
        json={
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 256
        },
        timeout=timeout
    )
    
    response.raise_for_status()
    result = response.json()
    
    # 解析返回内容
    content = result["choices"][0]["message"]["content"]
    
    # 清理可能的 markdown 代码块
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    # 解析 JSON
    parsed = json.loads(content)
    
    # 确保必要字段存在
    return {
        "intent": parsed.get("intent", "general_chat"),
        "entities": parsed.get("entities", {}),
        "plan": parsed.get("plan", []),
        "confidence": parsed.get("confidence", 0.8),
        "raw_text": text
    }


def get_nlu_and_plan_with_fallback(
    text: str,
    model_url: str = DEFAULT_MODEL_URL,
    model_name: str = DEFAULT_MODEL_NAME,
    timeout: int = 30,
    fallback_to_rule: bool = True
) -> Dict[str, Any]:
    """
    带兜底的 NLU/Planner
    
    如果模型调用失败，回退到规则模式
    """
    try:
        return get_nlu_and_plan(text, model_url, model_name, timeout)
    except Exception as e:
        if fallback_to_rule:
            print(f"[WARN] Model call failed: {e}, fallback to rule-based")
            return rule_based_nlu(text)
        raise


def rule_based_nlu(text: str) -> Dict[str, Any]:
    """
    基于规则的 NLU（兜底方案）
    """
    text_lower = text.lower()
    
    # 简单规则匹配
    intent = "general_chat"
    entities = {}
    plan = []
    
    # 商品咨询
    if any(kw in text_lower for kw in ["推荐", "精华", "面霜", "面膜", "产品"]):
        intent = "product_qa"
        plan = [{"skill_name": "rag"}, {"skill_name": "generation"}]
        
        # 提取产品类型
        if "精华" in text:
            entities["product_type"] = "serum"
        elif "面霜" in text:
            entities["product_type"] = "cream"
        elif "面膜" in text:
            entities["product_type"] = "mask"
    
    # 肤质分析
    elif any(kw in text_lower for kw in ["肤质", "油皮", "干皮", "敏感"]):
        intent = "skin_analysis"
        plan = [{"skill_name": "skin_analysis"}]
        
        if "油" in text:
            entities["skin_type"] = "oily"
        elif "干" in text:
            entities["skin_type"] = "dry"
        elif "敏感" in text:
            entities["skin_type"] = "sensitive"
    
    # 提取关注点
    if any(kw in text_lower for kw in ["痘", "痘痘", "粉刺"]):
        entities["concern"] = "acne"
    elif any(kw in text_lower for kw in ["敏感", "泛红", "过敏"]):
        entities["concern"] = "sensitive"
    elif any(kw in text_lower for kw in ["干燥", "干", "补水"]):
        entities["concern"] = "dryness"
    
    # 默认 plan
    if not plan:
        plan = [{"skill_name": "generation"}]
    
    return {
        "intent": intent,
        "entities": entities,
        "plan": plan,
        "confidence": 0.6,
        "raw_text": text,
        "fallback": True
    }


# 测试代码
if __name__ == "__main__":
    # 测试用例
    test_cases = [
        "我长痘了，推荐个精华",
        "我是敏感肌，适合什么面霜",
        "你好",
        "这个产品怎么用"
    ]
    
    print("=" * 60)
    print("NLU/Planner 直接调用测试")
    print("=" * 60)
    
    for text in test_cases:
        print(f"\n用户输入: {text}")
        try:
            result = get_nlu_and_plan_with_fallback(text)
            print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        except Exception as e:
            print(f"错误: {e}")

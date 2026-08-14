"""多查询改写服务 —— 检索质量专线·阶段4。

背景（见 eval/ 评测结论 + 阶段3 复盘）：正例召回已近满分，但个别 hard case 漏召回
（#8/#55），且用户问法与文档措辞用词不一致时，单条查询的向量召回可能错过相关片段。
rerank 精排解决不了「压根没召回进候选池」的漏召回；多查询改写从**召回侧**补强：
让 LLM 把原问题改写成若干语义等价、但措辞/角度不同的查询，各自召回后合并去重，
用「多个入口」覆盖同一答案的不同表述，提升 Recall。

实现：DeepSeek urllib 直连（复用 answer_service 的成熟风格与账号），一次调用产出 N 条改写。
provider 开关：QUERY_REWRITE_PROVIDER=fake 走确定性启发式（加检索向友好后缀），供单测零网络。

失败降级：改写是「召回增强」而非「必需」。任何网络/解析异常都返回空列表 []，调用方退回
「只用原查询」——增强层故障绝不能拖垮检索主流程。
"""

import json
from urllib import request
from urllib.error import URLError, HTTPError

from app.config import (
    QUERY_REWRITE_PROVIDER,
    DEEPSEEK_API_KEY,
    DEEPSEEK_CHAT_MODEL,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 改写生成的系统指令：要点——只做「同义/换角度」改写，不改变问题意图，不加入新信息。
# 输出严格 JSON 数组，便于解析（DeepSeek thinking 模型可能夹带思考文字，故用正则抠数组）。
_REWRITE_PROMPT = (
    "你是企业知识库检索的查询改写助手。用户会给你一个【原始问题】，"
    "请把它改写成若干个语义等价、但措辞或提问角度不同的检索查询，"
    "用于从文档库中更全面地召回相关内容。\n"
    "要求：\n"
    "1. 保持原问题的意图与关键实体不变，只换表达方式/近义词/提问角度。\n"
    "2. 不要引入原问题没有的新信息或新约束。\n"
    "3. 每条尽量简洁，像一个独立的检索查询。\n"
    "只输出一个 JSON 字符串数组，不要输出数组以外的任何文字，例如：\n"
    '["改写1", "改写2", "改写3"]'
)


def _fake_rewrite(question: str, n: int) -> list[str]:
    """测试/离线用的确定性改写：不发网络请求。

    规则简单可预测：在原问题上加不同的检索向后缀，产出 n 条不同字符串，便于单测断言。
    """
    suffixes = ["的方法", "怎么做", "是什么", "的步骤", "的原理", "如何实现"]
    return [f"{question}{suffixes[i % len(suffixes)]}" for i in range(n)]


def _deepseek_rewrite(question: str, n: int) -> list[str]:
    """真实改写：DeepSeek urllib 直连，一次调用产出 N 条改写。异常向上抛，由 rewrite 兜底降级。"""
    url = "https://api.deepseek.com/v1/chat/completions"
    user_content = f"【原始问题】\n{question}\n\n请给出 {n} 条改写。"
    payload = {
        "model": DEEPSEEK_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _REWRITE_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    text = (response_data["choices"][0]["message"]["content"] or "").strip()

    # 解析 JSON 数组：thinking 模型可能在数组前后带思考文字，抠出第一个 [...] 块。
    import re

    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError(f"改写返回无法解析为 JSON 数组：{text[:120]}")
    arr = json.loads(match.group(0))

    # 规整：只保留非空字符串、去掉与原问题完全相同的、去重、截断到 n 条。
    seen = set()
    result: list[str] = []
    for item in arr:
        s = str(item).strip()
        if not s or s == question.strip() or s in seen:
            continue
        seen.add(s)
        result.append(s)
        if len(result) >= n:
            break
    return result


def rewrite(question: str, n: int = 3) -> list[str]:
    """把原问题改写成至多 n 条语义等价查询，返回改写句列表（不含原问题）。

    ★失败降级★：任何异常都不上抛，返回空列表 []，调用方退回「只用原查询」。
    改写是召回增强而非必需，其故障绝不能中断检索主流程。
    """
    if n <= 0 or not question or not question.strip():
        return []

    try:
        if QUERY_REWRITE_PROVIDER == "fake":
            return _fake_rewrite(question, n)
        if QUERY_REWRITE_PROVIDER == "deepseek":
            return _deepseek_rewrite(question, n)
        raise ValueError(f"Unsupported query rewrite provider: {QUERY_REWRITE_PROVIDER}")
    except (HTTPError, URLError, TimeoutError, ConnectionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.warning(f"查询改写失败，降级为只用原查询：{type(exc).__name__}: {exc}")
        return []
    except Exception as exc:  # noqa: BLE001 —— 兜底：改写失败绝不拖垮检索
        logger.warning(f"查询改写异常，降级为只用原查询：{type(exc).__name__}: {exc}")
        return []

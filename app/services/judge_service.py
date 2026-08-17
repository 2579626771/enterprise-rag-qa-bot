"""答案层「研判」防幻觉服务。

背景（见 eval/ 评测结论）：
主题相关但库里没答案的问题（hard-negative），其检索距离与「真能回答」的问题几乎完全
重叠——单靠 RAG_MAX_DISTANCE 距离阈值无法区分，大模型会拿「答非所问」的片段硬编，
产生幻觉（基线幻觉风险率 91.7%）。

研判层的做法：作答时先让 LLM 判断「这些资料是否真能回答该问题」，
- 能答 → 正常作答；
- 不能答 → 明确拒答，绝不编造。
一次 LLM 调用同时完成「研判 + 作答」，返回结构化结果 {answerable, reason, answer, confidence}。

实现走 LangChain 的 ChatOpenAI(指向 DeepSeek 的 OpenAI 兼容端点) + with_structured_output，
结构化输出比手工解析 JSON 更稳。provider 复用 answer_service 的 ANSWER_PROVIDER：
- fake：确定性启发式，不发网络请求，供单元测试与离线开发；
- deepseek：真实 LLM 研判。

健壮性：任何一步失败（网络、SSL、解析）都不该让问答主流程崩。judge 出错时返回
degraded 结果（answerable=True 放行 + confidence=low + reason 标注研判失败），
让上层回退到「照常作答」，绝不因为防幻觉功能本身的故障而拒绝服务。
"""

import time

from app.config import (
    ANSWER_PROVIDER,
    DEEPSEEK_API_KEY,
    DEEPSEEK_CHAT_MODEL,
    DEEPSEEK_BASE_URL,
)
from app.utils.logger import get_logger
from app.services import model_usage_service as model_usage

logger = get_logger(__name__)

# 拒答时对用户展示的话术（与 rag_service 无相关内容时的话术保持一致风格）。
REFUSAL_TEXT = "根据现有资料，无法回答这个问题。可换个问法，或补充相关文档后再试。"

# 研判 + 作答的系统提示。要点：宁可拒答不可编造；资料不足要给出「缺什么」的理由。
# 输出用 JSON：DeepSeek 的 thinking 模型不支持 OpenAI 的 response_format/强制 tool_choice
# （实测报 "response_format type is unavailable" / "Thinking mode does not support tool_choice"），
# 故不用 LangChain 的 with_structured_output，改为「提示模型输出 JSON + 手工解析」，更稳、更通用。
_JUDGE_SYSTEM_PROMPT = (
    "你是一个严谨的企业知识库问答助手。你会收到一个【问题】和若干【资料】片段"
    "（从文档中检索而来，可能顺序打乱、夹杂无关内容）。\n"
    "请严格按以下步骤处理：\n"
    "1. 先判断【资料】里是否真的包含能回答【问题】的信息。\n"
    "   - 注意：资料的主题与问题相关，不等于资料里有答案。例如资料在讲某产品的"
    "Windows 防护，而问题问的是它是否支持 Mac —— 若资料并未提及 Mac，就是「无法回答」。\n"
    "   - 只有当资料中确有可支撑答案的具体内容时，才算「能回答」。\n"
    "2. 如果能回答：基于资料作答，可归纳整理，但不得引入资料之外的编造内容。\n"
    "3. 如果不能回答：不要用常识/外部知识硬答。\n"
    "始终以资料为唯一依据。宁可诚实拒答，也不要编造。\n\n"
    "只输出一个 JSON 对象，不要输出 JSON 以外的任何文字，格式如下：\n"
    '{"answerable": true 或 false, '
    '"reason": "判断理由；不能回答时说明资料里缺了什么", '
    '"answer": "能回答时基于资料的答案；不能回答时留空字符串", '
    '"confidence": "high 或 low"}'
)


def _fake_judge_and_answer(question: str, context: str) -> dict:
    """测试/离线用的确定性研判：不发网络请求。

    规则简单可预测，便于单测断言：
    - context 为空/纯空白 → 判为不能回答（answerable=False）。
    - 否则 → 判为能回答，answer 把问题与资料拼接回显（与 answer_service 的 fake 风格一致）。
    """
    if not context or not context.strip():
        return {
            "answerable": False,
            "reason": "（fake）没有任何资料，无法回答。",
            "answer": REFUSAL_TEXT,
            "confidence": "low",
        }
    return {
        "answerable": True,
        "reason": "（fake）资料非空，判为可回答。",
        "answer": f"根据检索到的内容:{context},可以回答你的问题:{question}",
        "confidence": "high",
    }


def _deepseek_judge_and_answer(question: str, context: str) -> dict:
    """真实研判：LangChain ChatOpenAI(DeepSeek) + 结构化输出，一次调用完成研判+作答。

    任何异常都不向上抛，转为 degraded 放行结果（answerable=True + confidence=low），
    让上层回退到「照常作答」——防幻觉功能自身的故障绝不能拖垮问答主流程。
    """
    start = time.perf_counter()
    try:
        # 局部导入：只有真正启用 deepseek 研判时才加载 LangChain，
        # 未启用 JUDGE_ENABLED / 走 fake 时零依赖、零副作用。
        import json
        import re
        from langchain_openai import ChatOpenAI

        # 内网 SSL：现有 urllib 路径靠 pip-system-certs 走系统证书库；但 LangChain 底层用的是
        # httpx（openai 客户端），它自建 SSL 上下文、不读系统证书库，会导致公司安全网关拦截 HTTPS
        # 时握手失败（Connection error）。用 truststore 把 Python SSL 接到 Windows 系统信任库，
        # 一次注入即可让 httpx 也走系统证书。失败则忽略（非内网环境本就不需要）。
        try:
            import os

            # 防御：httpx 会读环境变量 SSL_CERT_FILE 并 load_verify_locations()，
            # 若该变量指向一个不存在的文件（例如别的项目残留的路径），会直接抛
            # FileNotFoundError。这里在注入 truststore 前清掉「指向不存在文件」的该变量，
            # 让 truststore/系统信任库接管，避免被无关的环境残留搞崩。
            cert_file = os.environ.get("SSL_CERT_FILE")
            if cert_file and not os.path.exists(cert_file):
                logger.warning(f"SSL_CERT_FILE 指向不存在的文件，已忽略：{cert_file}")
                os.environ.pop("SSL_CERT_FILE", None)

            import truststore

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001
            pass

        llm = ChatOpenAI(
            model=DEEPSEEK_CHAT_MODEL,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            temperature=0,      # 研判要稳定可复现，不要发散
            timeout=60,
            max_retries=2,
        )

        user_content = f"【问题】\n{question}\n\n【资料】\n{context}"
        start = time.perf_counter()
        response = llm.invoke(
            [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        usage = model_usage.extract_langchain_usage(response)
        text = (response.content or "").strip()

        # 解析 JSON：thinking 模型可能在 JSON 前后带思考文字，抠出第一个 {...} 块。
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"研判返回无法解析为 JSON：{text[:120]}")
        verdict = json.loads(match.group(0))

        answerable = bool(verdict.get("answerable"))
        reason = str(verdict.get("reason") or "")
        raw_answer = str(verdict.get("answer") or "")
        confidence = verdict.get("confidence")
        confidence = confidence if confidence in {"high", "low"} else "low"

        model_usage.record_call(
            model_type=model_usage.MODEL_JUDGE,
            provider="deepseek",
            model_name=DEEPSEEK_CHAT_MODEL,
            operation="judge_answer",
            success=True,
            latency_ms=(time.perf_counter() - start) * 1000,
            input_count=1,
            **usage,
        )

        if not answerable:
            # 拒答：统一话术，不采用模型可能编造的 answer 文本。
            return {
                "answerable": False,
                "reason": reason or "资料中没有能回答该问题的信息。",
                "answer": REFUSAL_TEXT,
                "confidence": "low",
            }
        return {
            "answerable": True,
            "reason": reason,
            "answer": raw_answer,
            "confidence": confidence,
        }
    except Exception as exc:  # noqa: BLE001 —— 故意兜底：研判失败不拖垮主流程
        model_usage.record_call(
            model_type=model_usage.MODEL_JUDGE,
            provider="deepseek",
            model_name=DEEPSEEK_CHAT_MODEL,
            operation="judge_answer",
            success=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            input_count=1,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        logger.warning(f"研判调用失败，降级为放行照常作答：{type(exc).__name__}: {exc}")
        return {
            "answerable": True,
            "reason": f"（研判不可用，已降级照常作答：{type(exc).__name__}）",
            "answer": "",          # 空 answer 让上层回退到常规 generate_answer
            "confidence": "low",
            "degraded": True,
        }


def judge_and_answer(question: str, context: str) -> dict:
    """研判并作答的统一入口。

    返回 dict：
    - answerable (bool)：资料是否真能回答该问题。
    - reason (str)：判断理由（拒答时说明缺什么）。
    - answer (str)：能答时的答案；拒答时为拒答话术；degraded 时为空串。
    - confidence ("high"|"low")：可信度。
    - degraded (bool, 可选)：研判失败已降级放行时为 True。

    provider 复用 ANSWER_PROVIDER：fake 走确定性启发式，deepseek 走真实 LLM。
    """
    if ANSWER_PROVIDER == "fake":
        return _fake_judge_and_answer(question, context)
    if ANSWER_PROVIDER == "deepseek":
        return _deepseek_judge_and_answer(question, context)
    raise ValueError(f"Unsupported answer provider for judge: {ANSWER_PROVIDER}")

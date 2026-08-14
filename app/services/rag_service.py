from app.services.answer_service import generate_answer
from app.services import knowledge_base_service
from app.config import RAG_TOP_K, RAG_MAX_DISTANCE, JUDGE_ENABLED
from app.utils.logger import get_logger
logger = get_logger(__name__)


def answer_from_knowledge_base(
    question: str,
    top_k: int | None = None,
    kb_id: int | None = None,
    kb_ids: list[int] | None = None,
) -> dict:
    """知识库问答：在指定范围内检索，再让大模型据此回答。

    检索范围（互斥，kb_ids 优先）：
    - kb_ids：在这批库里检索（「全部知识库」——普通用户传自己拥有的所有库 id，天然隔离）。
    - kb_id：只在该单库检索（普通用户单选某库）。
    - 两者都 None：真全库（仅管理员跨库）。

    返回：answer(回答) + sources(命中的来源列表) + answerable/reason/confidence(研判结果)。
    研判(JUDGE_ENABLED)开启时，作答前先判断「资料是否真能回答该问题」，不能答则明确拒答，
    治「主题相关但库里没答案」导致的幻觉（详见 judge_service 与 eval/ 评测结论）。
    """
    if top_k is None:
        top_k = RAG_TOP_K

    hits = knowledge_base_service.search(question, top_k=top_k, kb_id=kb_id, kb_ids=kb_ids)

    # ★第一道防线：相似度阈值过滤★
    # 检索一定会返回 top_k 条，哪怕都不相关。这里把“距离太远（不够相关）”的丢掉。
    # 距离越小越相关；大于阈值的视为无关。
    relevant_hits = [hit for hit in hits if hit["distance"] <= RAG_MAX_DISTANCE]

    if hits:
        logger.info(
            f"检索到 {len(hits)} 条，距离={[round(h['distance'], 3) for h in hits]}，"
            f"阈值={RAG_MAX_DISTANCE}，通过过滤 {len(relevant_hits)} 条"
        )

    if not relevant_hits:
        # 要么库是空的，要么没有一条足够相关 —— 都不让大模型硬答，避免编造。
        logger.info(f"无足够相关内容，问题：{question}")
        return {
            "answer": "知识库中没有找到与该问题相关的内容。请换个问法，或先上传/入库相关文档。",
            "sources": [],
            "answerable": False,
            "reason": "检索结果为空或均不相关（距离超过阈值）。",
            "confidence": "low",
        }

    # 把命中的若干段文字拼成“资料”，交给大模型作答。
    context_parts = [hit["content"].replace("\n", " ") for hit in relevant_hits]
    context = "\n---\n".join(context_parts)

    logger.info(f"用户问题：{question}")
    logger.info(f"命中来源：{[(h['filename'], h['chunk_index']) for h in relevant_hits]}")

    sources = [
        {
            "filename": hit["filename"],
            "chunk_index": hit["chunk_index"],
            "content": hit["content"],
        }
        for hit in relevant_hits
    ]

    # ★第二道防线：研判层（防幻觉）★
    # 距离阈值挡不住「主题相关但库里没答案」的问题（评测证明两者距离几乎完全重叠）。
    # 研判层让 LLM 判断资料是否真能回答；不能答则明确拒答、保留来源供用户自查。
    if JUDGE_ENABLED:
        from app.services.judge_service import judge_and_answer

        verdict = judge_and_answer(question=question, context=context)
        # degraded：研判自身失败已降级放行，answer 为空 —— 回退到常规作答，绝不因研判故障拒服务。
        if verdict.get("degraded") or not verdict.get("answer"):
            answer = generate_answer(question=question, context=context)
        else:
            answer = verdict["answer"]

        if not verdict["answerable"]:
            logger.info(f"研判判定不可回答：{verdict.get('reason', '')}")
        logger.info(f"生成的回答: {answer}")
        return {
            "answer": answer,
            "sources": sources,
            "answerable": verdict["answerable"],
            "reason": verdict.get("reason", ""),
            "confidence": verdict.get("confidence", "low"),
        }

    # 研判关闭：走原有流程（行为与引入前完全一致）。
    answer = generate_answer(question=question, context=context)
    logger.info(f"生成的回答: {answer}")
    return {
        "answer": answer,
        "sources": sources,
        "answerable": True,
        "reason": "",
        "confidence": "high",
    }


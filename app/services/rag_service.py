from app.services.answer_service import generate_answer
from app.services import knowledge_base_service
from app.config import RAG_TOP_K, RAG_MAX_DISTANCE
from app.utils.logger import get_logger
logger = get_logger(__name__)


def answer_from_knowledge_base(question: str, top_k: int | None = None, kb_id: int | None = None) -> dict:
    """知识库问答：在指定知识库范围内检索，再让大模型据此回答。

    kb_id 非空时只在该知识库检索（普通用户）；为 None 时全库检索（管理员跨库）。

    返回：answer(回答) + sources(命中的来源列表，标明来自哪个文件、哪一段)。
    """
    if top_k is None:
        top_k = RAG_TOP_K

    hits = knowledge_base_service.search(question, top_k=top_k, kb_id=kb_id)

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
        }

    # 把命中的若干段文字拼成“资料”，交给大模型作答。
    context_parts = [hit["content"].replace("\n", " ") for hit in relevant_hits]
    context = "\n---\n".join(context_parts)

    logger.info(f"用户问题：{question}")
    logger.info(f"命中来源：{[(h['filename'], h['chunk_index']) for h in relevant_hits]}")

    answer = generate_answer(question=question, context=context)
    logger.info(f"生成的回答: {answer}")

    sources = [
        {
            "filename": hit["filename"],
            "chunk_index": hit["chunk_index"],
            "content": hit["content"],
        }
        for hit in relevant_hits
    ]

    return {
        "answer": answer,
        "sources": sources,
    }

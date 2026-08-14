"""检索重排（rerank）服务 —— 检索质量专线·阶段3。

背景（见 eval/ 评测结论）：本系统正例召回已近满分，但「能答/不能答」在向量距离上区间
重叠，且个别 hard case 漏召回（评测里的 #8/#55）。rerank 用交叉编码器（cross-encoder）
对「query-候选片段」逐对精排，比双塔向量的粗排更能拉开相关/不相关的分差、把真正相关的
片段顶到前面。

实现：阿里云百炼 gte-rerank-v2，纯 HTTP（urllib 直连，仿 embedding_service 的健壮性风格），
复用同一个 ALIYUN_API_KEY，无需 torch/本地模型，内网友好（NO_PROXY 已含 dashscope）。

设计要点：
- rerank 只负责「重新排序候选」，返回每条候选的新次序与相关性分数；是否截断、如何与
  向量距离阈值配合，由调用方（knowledge_base_service.search）决定。
- 失败降级：rerank 是「增强」而非「必需」。任何网络/解析异常都不上抛，返回「保持原顺序」
  的结果，让检索主流程照常进行——增强层的故障绝不能拖垮问答。
- provider 开关：RERANK_PROVIDER=fake 走确定性启发式（字符重叠度），供单测零网络。
"""

import json
from urllib import request
from urllib.error import URLError, HTTPError
from http.client import IncompleteRead

from app.config import (
    RERANK_PROVIDER,
    ALIYUN_API_KEY,
    ALIYUN_RERANK_MODEL,
    ALIYUN_RERANK_URL,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# HTTP 健壮性参数（与 embedding_service 同构）：rerank 是远程 HTTP 服务，
# 网络抖动/连接中断可重试；4xx（非 429）通常是请求本身有问题，不重试。
_HTTP_MAX_RETRIES = 3
_HTTP_BACKOFF_BASE = 1.0
_HTTP_TIMEOUT = 30


def _fake_rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    """测试/离线用的确定性重排：不发网络请求。

    规则：按「候选与 query 的字符集合重叠度」降序（重叠越多越相关），可预测、便于断言。
    返回与真实接口同构的 [{index, relevance_score}]，index 指向原 documents 下标。
    """
    q_chars = set(query)
    scored = []
    for i, doc in enumerate(documents):
        overlap = len(q_chars & set(doc))
        score = overlap / (len(q_chars) or 1)
        scored.append({"index": i, "relevance_score": score})
    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:top_n]


def _aliyun_rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    """真实重排：阿里云 gte-rerank-v2。返回 [{index, relevance_score}]（按相关性降序）。

    接口契约（已实测）：
      POST {ALIYUN_RERANK_URL}
      body: {model, input:{query, documents}, parameters:{top_n, return_documents:false}}
      resp: {output:{results:[{index, relevance_score}, ...]}, usage, request_id}
      results 已按 relevance_score 降序，index 指向传入 documents 的下标。
    """
    payload = {
        "model": ALIYUN_RERANK_MODEL,
        "input": {"query": query, "documents": documents},
        # return_documents=false：只要次序与分数，不回传文档原文，省带宽（原文我们本地已有）。
        "parameters": {"top_n": top_n, "return_documents": False},
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {ALIYUN_API_KEY}",
        "Content-Type": "application/json",
    }

    import time

    last_exc: Exception | None = None
    for attempt in range(_HTTP_MAX_RETRIES):
        try:
            req = request.Request(url=ALIYUN_RERANK_URL, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=_HTTP_TIMEOUT) as response:
                raw = response.read()
            resp = json.loads(raw.decode("utf-8"))
            results = resp.get("output", {}).get("results", [])
            # 规整：只保留 index/relevance_score，且过滤越界 index（防御）。
            cleaned = [
                {"index": int(r["index"]), "relevance_score": float(r.get("relevance_score", 0.0))}
                for r in results
                if 0 <= int(r.get("index", -1)) < len(documents)
            ]
            return cleaned
        except HTTPError as exc:
            if exc.code != 429 and 400 <= exc.code < 500:
                raise  # 4xx（非限流）不重试，交给上层降级
            last_exc = exc
        except (IncompleteRead, URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last_exc = exc

        if attempt < _HTTP_MAX_RETRIES - 1:
            time.sleep(_HTTP_BACKOFF_BASE * (2 ** attempt))

    raise RuntimeError(
        f"rerank 请求失败（已重试 {_HTTP_MAX_RETRIES} 次）：{type(last_exc).__name__}: {last_exc}"
    )


def rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    """对候选文档按与 query 的相关性重排，返回 [{index, relevance_score}]（降序，最多 top_n 条）。

    index 指向传入 documents 的下标，供调用方按新次序取回原候选对象。

    ★失败降级★：任何异常都不上抛，返回「保持原顺序」的 top_n 条（relevance_score 置 0）。
    rerank 是检索增强而非必需，其故障绝不能中断问答主流程。
    """
    if not documents:
        return []
    top_n = min(top_n, len(documents))

    try:
        if RERANK_PROVIDER == "fake":
            return _fake_rerank(query, documents, top_n)
        if RERANK_PROVIDER == "aliyun":
            return _aliyun_rerank(query, documents, top_n)
        raise ValueError(f"Unsupported rerank provider: {RERANK_PROVIDER}")
    except Exception as exc:  # noqa: BLE001 —— 故意兜底：rerank 失败退回原顺序，不拖垮检索
        logger.warning(f"rerank 调用失败，降级为保持原顺序：{type(exc).__name__}: {exc}")
        return [{"index": i, "relevance_score": 0.0} for i in range(top_n)]

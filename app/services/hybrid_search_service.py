"""BM25 + jieba 混合检索服务（检索质量专线·阶段2/6）。

设计目标：
- 作为向量召回的补充，覆盖精确词、缩写、口语中关键词很强但向量排名不够靠前的场景。
- 只在调用方已经确定的 where/kb 范围内取片段，绝不参与范围决策，避免破坏多租户隔离。
- 不引入重型搜索引擎；本地按当前范围片段临时计算 BM25，适合现阶段中小规模知识库。
- jieba 不可用时降级为简单字符/英文 token 分词，保证主链路不因增强层依赖失败而崩。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from app.config import HYBRID_RRF_K

_WORD_RE = re.compile(r"[A-Za-z0-9_+.#-]+")
_CJK_RE = re.compile(r"[一-鿿]")


def tokenize(text: str) -> list[str]:
    """中文优先用 jieba；失败时用英文词 + 单汉字兜底。"""
    text = (text or "").strip().lower()
    if not text:
        return []
    try:
        import jieba  # type: ignore

        tokens = [t.strip().lower() for t in jieba.lcut(text) if t.strip()]
        # jieba 对英文/符号有时会粘连；补充正则英文 token，提高英文关键词命中稳定性。
        tokens.extend(_WORD_RE.findall(text))
        return [t for t in tokens if len(t) > 1 or _CJK_RE.fullmatch(t)]
    except Exception:  # noqa: BLE001 —— 增强层依赖失败时必须可降级
        tokens = _WORD_RE.findall(text)
        tokens.extend(_CJK_RE.findall(text))
        return tokens


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], idf: dict[str, float], avgdl: float) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    k1 = 1.5
    b = 0.75
    score = 0.0
    for term in query_tokens:
        freq = tf.get(term, 0)
        if freq <= 0:
            continue
        denom = freq + k1 * (1 - b + b * dl / (avgdl or 1.0))
        score += idf.get(term, 0.0) * (freq * (k1 + 1)) / denom
    return score


def bm25_rank(question: str, documents: list[dict], top_k: int) -> list[dict]:
    """对已限定范围的 documents 做 BM25 排序，返回带 bm25_score 的候选。"""
    if top_k <= 0 or not documents:
        return []
    query_tokens = tokenize(question)
    if not query_tokens:
        return []

    tokenized = [tokenize(d.get("content", "")) for d in documents]
    n_docs = len(tokenized)
    avgdl = sum(len(toks) for toks in tokenized) / n_docs if n_docs else 0.0

    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    idf = {
        term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
        for term, freq in df.items()
    }

    scored = []
    for doc, toks in zip(documents, tokenized):
        score = _bm25_score(query_tokens, toks, idf, avgdl)
        if score > 0:
            enriched = dict(doc)
            enriched["bm25_score"] = score
            scored.append(enriched)
    scored.sort(key=lambda d: d["bm25_score"], reverse=True)
    return scored[: min(top_k, len(scored))]


def rrf_merge(vector_candidates: list[dict], bm25_candidates: list[dict], *, rrf_k: int | None = None) -> list[dict]:
    """用 Reciprocal Rank Fusion 合并向量与 BM25 排名。

    RRF 不依赖原始分数同尺度，适合融合“向量距离（越小越好）”和“BM25 分数（越大越好）”。
    distance 保留向量候选的原始值；BM25-only 候选若无向量距离，distance 置为 0.5，避免被
    阈值第一道防线无条件丢弃。最终是否能回答仍交给研判层判断。
    """
    k = rrf_k if rrf_k is not None else HYBRID_RRF_K
    merged: dict[tuple, dict] = {}
    scores: dict[tuple, float] = {}

    def key_of(item: dict) -> tuple:
        return (item.get("filename", ""), item.get("chunk_index", -1))

    for rank, item in enumerate(vector_candidates, start=1):
        key = key_of(item)
        merged[key] = dict(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    for rank, item in enumerate(bm25_candidates, start=1):
        key = key_of(item)
        if key not in merged:
            enriched = dict(item)
            enriched.setdefault("distance", 0.5)
            merged[key] = enriched
        else:
            if "bm25_score" in item:
                merged[key]["bm25_score"] = item["bm25_score"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    for key, item in merged.items():
        item["rrf_score"] = scores.get(key, 0.0)
    return sorted(merged.values(), key=lambda item: item.get("rrf_score", 0.0), reverse=True)


def rows_from_collection(collection, where: dict | None) -> list[dict]:
    """从 Chroma 当前限定范围读取片段，供 BM25 使用。"""
    raw = collection.get(where=where, include=["documents", "metadatas"]) if where else collection.get(include=["documents", "metadatas"])
    rows = []
    for doc, metadata in zip(raw.get("documents") or [], raw.get("metadatas") or []):
        meta = metadata or {}
        rows.append(
            {
                "content": doc or "",
                "filename": meta.get("filename", ""),
                "chunk_index": meta.get("chunk_index", -1),
                "distance": 0.5,
            }
        )
    return rows


def hybrid_rank(
    question: str,
    vector_candidates: list[dict],
    bm25_documents: Iterable[dict],
    bm25_top_k: int,
) -> list[dict]:
    """向量候选 + BM25 候选 RRF 融合。"""
    bm25_candidates = bm25_rank(question, list(bm25_documents), top_k=bm25_top_k)
    return rrf_merge(vector_candidates, bm25_candidates)

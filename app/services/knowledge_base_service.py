"""
知识库服务（Chroma 版）。

打个比方：这个文件就是“档案柜管理员”。
- 档案柜 = Chroma 向量库，存在硬盘上（程序重启数据还在）。
- 柜子里放的每张“卡片” = 文档的一个小片段(chunk) + 它的向量(embedding) + 备注(来自哪个文件)。
- 管理员只对外提供三件事：
    1. ingest_document  把一个文档拆成卡片、算好向量、放进柜子（入库）
    2. search           拿问题的向量去柜子里找最像的前 K 张卡片（检索）
    3. delete_document  按文件名把某个文档的所有卡片抽出来扔掉（删除）

主流程(rag_service / api)只跟这个管理员打交道，不直接碰 Chroma。
好处：将来想把 Chroma 换成别的向量库，只改这一个文件就行。
"""

import chromadb

from app.config import CHROMA_DIR, CHROMA_COLLECTION
from app.schemas.document import Document
from app.services.document_service import split_document_by_paragraphs
from app.services.embedding_service import (
    create_embeddings_for_chunks,
    create_query_embedding,
)

# 全局只创建一个“客户端”和一个“集合”，避免每次调用都重新打开档案柜。
_client = None
_collection = None


def get_collection():
    """拿到（必要时先创建）知识库集合。

    metadata={'hnsw:space': 'cosine'} 是关键：告诉 Chroma 用“余弦相似度”找相似，
    也就是比“两串数字的方向像不像”，而不是比“绝对距离”。这样长短不同但主题相同的
    两段文字也能正确判为相关。
    """
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _get_public_client():
    """拿到当前生效的**公共** chromadb 客户端（ClientAPI）。

    langchain_chroma 需要公共 Client（PersistentClient/EphemeralClient 返回的对象），
    不能用 collection._client（那是底层 RustBindingsAPI，签名不同会崩）。

    - 生产/正常路径：get_collection() 已初始化 _client（PersistentClient），直接返回。
    - 测试注入路径：_set_collection_for_test 会连同注入的集合一并把它的公共 client
      存进 _client，这里取到的就是测试用的 EphemeralClient。
    """
    global _client
    if _client is None:
        # 确保已初始化（正常路径下 get_collection 会建 PersistentClient）。
        get_collection()
    return _client


def _make_point_id(kb_id: int, filename: str, chunk_index: int) -> str:
    """给每张卡片起一个唯一编号，格式：kb_id::文件名::片段序号。

    带上 kb_id 是为了防止不同知识库的同名文件互相覆盖（复合隔离）。
    同一知识库内同一文件重新入库时，编号不变，Chroma 会“覆盖”而不是“重复堆积”。
    """
    return f"{kb_id}::{filename}::{chunk_index}"


def ingest_document(document: Document, kb_id: int) -> dict:
    """把一个文档存进指定知识库（入库）。

    步骤：切分成段落 -> 每段算向量 -> 连同“来自哪个文件 + 属于哪个知识库”一起写进档案柜。
    返回入库了多少个片段。
    """
    collection = get_collection()

    chunks = split_document_by_paragraphs(document)
    if not chunks:
        return {"filename": document.filename, "chunk_count": 0}

    embeddings = create_embeddings_for_chunks(chunks)

    ids = []
    vectors = []
    documents_text = []
    metadatas = []

    for chunk, embedding in zip(chunks, embeddings):
        ids.append(_make_point_id(kb_id, document.filename, chunk.chunk_index))
        vectors.append(embedding.vector)
        documents_text.append(chunk.content)
        # 备注信息：来自哪个文件、第几段、属于哪个知识库。检索时用 kb_id 过滤做隔离。
        metadatas.append(
            {
                "kb_id": kb_id,
                "filename": document.filename,
                "chunk_index": chunk.chunk_index,
            }
        )

    # upsert = 有则覆盖、无则新增。保证同一文档重复入库不会堆出一堆重复卡片。
    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=documents_text,
        metadatas=metadatas,
    )

    return {"filename": document.filename, "chunk_count": len(chunks)}


def search(
    question: str,
    top_k: int,
    kb_id: int | None = None,
    kb_ids: list[int] | None = None,
) -> list[dict]:
    """检索最相关的前 top_k 段文字（含来源）。

    检索范围三选一（互斥，kb_ids 优先级最高）：
    - kb_ids 非空：在这批知识库范围内检索（Chroma where kb_id $in 过滤）。用于「全部知识库」——
      普通用户传入「自己拥有的所有库 id」，天然隔离，绝不会召回他人的库。
    - kb_ids 为空列表 []：该用户没有任何库，直接返回 []（不做无谓查询）。
    - kb_id 非空：只在该单个知识库检索（原有单库路径，行为不变）。
    - 两者都为 None：真全库检索（仅管理员的跨库场景使用）。

    每一项包含：content、filename、chunk_index、distance（越小越像）。
    为提升质量：先多召回，过滤过短碎片，不足再补齐，保证不空。
    """
    # kb_ids 优先：空列表表示「无任何库」，直接返回，避免误当成全库。
    if kb_ids is not None and len(kb_ids) == 0:
        return []

    collection = get_collection()

    total = collection.count()
    if total == 0:
        return []

    # 多召回候选（top_k 的若干倍），给"过滤碎片"留出补位空间。
    candidate_k = min(max(top_k * 4, top_k), total)

    # 范围过滤：kb_ids（多库）优先于 kb_id（单库）；都为 None 则不过滤（全库）。
    # ★多租户隔离红线★：这个 where 决定普通用户「全部」只能看自己的库，绝不能弱化。
    where = None
    if kb_ids is not None:
        where = {"kb_id": {"$in": kb_ids}}
    elif kb_id is not None:
        where = {"kb_id": kb_id}

    from app.config import (
        HYBRID_BM25_TOP_K_MULTIPLIER,
        MULTI_QUERY_COUNT,
        MULTI_QUERY_ENABLED,
        RERANK_ENABLED,
        RERANK_STRATEGY,
        RETRIEVAL_CONTEXT_MAX_CHARS,
        RETRIEVAL_CONTEXT_WINDOW,
        RETRIEVAL_MODE,
    )

    mode = (RETRIEVAL_MODE or "auto").strip().lower()
    valid_modes = {
        "auto", "vector", "multi_query", "rerank", "rerank_fusion",
        "hybrid", "hybrid_rerank_fusion",
    }
    if mode not in valid_modes:
        mode = "auto"

    multi_query_on = (mode == "auto" and MULTI_QUERY_ENABLED) or mode == "multi_query"
    hybrid_on = mode in {"hybrid", "hybrid_rerank_fusion"}
    rerank_on = (mode == "auto" and RERANK_ENABLED) or mode in {
        "rerank", "rerank_fusion", "hybrid_rerank_fusion",
    }
    rerank_strategy = "sort" if mode == "rerank" else RERANK_STRATEGY
    if mode == "rerank_fusion" and rerank_strategy == "sort":
        rerank_strategy = "weighted"
    if mode == "hybrid_rerank_fusion" and rerank_strategy == "sort":
        rerank_strategy = "weighted"

    # ★检索召回接入 LangChain（阶段1 地基）★
    # 经 langchain_chroma 的 similarity_search_with_score 召回，为后续检索增强（rerank、
    # 多查询等）铺地基。similarity_search_with_score 返回的 score 即 Chroma 原始余弦距离。
    from app.services.langchain_adapters import build_chroma_vectorstore

    vectorstore = build_chroma_vectorstore(_get_public_client(), collection.name)

    # ★多查询改写（multi-query，阶段4）★
    # auto 模式下兼容旧开关；显式 RETRIEVAL_MODE=multi_query 时强制开启。
    queries = [question]
    if multi_query_on:
        from app.services import query_rewrite_service

        rewrites = query_rewrite_service.rewrite(question, n=MULTI_QUERY_COUNT)
        queries.extend(rewrites)

    # 多路召回合并：key=(kb_id, filename, chunk_index)，值取「最小 distance」的那条候选。
    merged: dict[tuple, dict] = {}
    for q in queries:
        scored = vectorstore.similarity_search_with_score(q, k=candidate_k, filter=where)
        for doc, distance in scored:
            metadata = doc.metadata or {}
            key = (
                metadata.get("kb_id"),
                metadata.get("filename", ""),
                metadata.get("chunk_index", -1),
            )
            cand = {
                "content": doc.page_content,
                "kb_id": metadata.get("kb_id"),
                "filename": metadata.get("filename", ""),
                "chunk_index": metadata.get("chunk_index", -1),
                "distance": distance,
            }
            # 同一片段被多条查询召回时，保留距离最小（最相关）的那次，避免重复且不丢最优分。
            if key not in merged or distance < merged[key]["distance"]:
                merged[key] = cand

    # 按 distance 升序，得到与「单查询召回」同构的候选列表（下游 rerank/过滤逻辑完全复用）。
    candidates = sorted(merged.values(), key=lambda c: c["distance"])

    # ★混合检索（BM25+jieba）★
    # 只从已经限定 where 的范围内取片段，和向量候选 RRF 融合；不参与范围决策，不破坏隔离。
    if hybrid_on:
        from app.services import hybrid_search_service

        bm25_rows = hybrid_search_service.rows_from_collection(collection, where)
        bm25_top_k = min(max(top_k * HYBRID_BM25_TOP_K_MULTIPLIER, top_k), len(bm25_rows))
        candidates = hybrid_search_service.hybrid_rank(
            question, candidates, bm25_rows, bm25_top_k=bm25_top_k
        )

    # ★检索重排（rerank，阶段3/融合）★
    # sort 为旧纯 rerank；window/weighted 为阶段6新增融合策略。rerank 只改顺序、不改原 distance。
    if rerank_on and candidates:
        candidates = _apply_rerank(question, candidates, top_k=top_k, strategy=rerank_strategy)

    # 过短片段（标题、目录行等，如"业务用户创建""3.3 xxx 14"）几乎没有回答价值，先剔除。
    MIN_CONTENT_LEN = 15
    substantial = [c for c in candidates if len(c["content"].strip()) >= MIN_CONTENT_LEN]

    # 优先取有实质内容的前 top_k；不足则用剩余候选（含短片段）按相似度补齐，保证不空。
    hits = substantial[:top_k]
    if len(hits) < top_k:
        for c in candidates:
            if c not in hits:
                hits.append(c)
            if len(hits) >= top_k:
                break

    if RETRIEVAL_CONTEXT_WINDOW > 0 and hits:
        hits = _expand_hit_contexts(
            collection,
            hits,
            window=RETRIEVAL_CONTEXT_WINDOW,
            max_chars=RETRIEVAL_CONTEXT_MAX_CHARS,
            fallback_kb_id=kb_id,
        )

    return hits


def _apply_rerank(question: str, candidates: list[dict], top_k: int, strategy: str) -> list[dict]:
    """按指定策略应用 rerank，且保留每条候选的原始 distance。"""
    if not candidates:
        return candidates

    import app.config as config
    from app.services import rerank_service

    strategy = (strategy or "sort").strip().lower()
    if strategy not in {"sort", "window", "weighted"}:
        strategy = "sort"

    if strategy == "sort":
        order = rerank_service.rerank(
            question, [c["content"] for c in candidates], top_n=len(candidates)
        )
        ranked_idx = [o["index"] for o in order if 0 <= o.get("index", -1) < len(candidates)]
        seen = set(ranked_idx)
        reordered = [candidates[i] for i in ranked_idx]
        reordered.extend(candidates[i] for i in range(len(candidates)) if i not in seen)
        return reordered

    window_size = min(
        len(candidates),
        max(top_k, top_k * max(1, int(getattr(config, "RERANK_WINDOW_MULTIPLIER", 2)))),
    )
    prefix = candidates[:window_size]
    suffix = candidates[window_size:]
    order = rerank_service.rerank(question, [c["content"] for c in prefix], top_n=len(prefix))

    if strategy == "window":
        ranked_idx = [o["index"] for o in order if 0 <= o.get("index", -1) < len(prefix)]
        seen = set(ranked_idx)
        reordered = [prefix[i] for i in ranked_idx]
        reordered.extend(prefix[i] for i in range(len(prefix)) if i not in seen)
        return reordered + suffix

    # weighted：向量距离（越小越好）与 rerank 分（越大越好）归一化后加权。
    scores = {o["index"]: float(o.get("relevance_score", 0.0)) for o in order if 0 <= o.get("index", -1) < len(prefix)}
    distances = [float(c.get("distance", 0.5)) for c in prefix]
    min_d, max_d = min(distances), max(distances)
    min_s = min(scores.values()) if scores else 0.0
    max_s = max(scores.values()) if scores else 0.0
    weight = min(1.0, max(0.0, float(getattr(config, "RERANK_WEIGHT", 0.6))))

    def norm_distance(value: float) -> float:
        if max_d == min_d:
            return 0.0
        return (value - min_d) / (max_d - min_d)

    def norm_score(value: float) -> float:
        if max_s == min_s:
            return 0.0
        return (value - min_s) / (max_s - min_s)

    weighted = []
    for idx, cand in enumerate(prefix):
        rerank_score = scores.get(idx, min_s)
        # combined 越小越靠前：距离越小越好，rerank 越大越好。
        combined = (1 - weight) * norm_distance(float(cand.get("distance", 0.5))) + weight * (1 - norm_score(rerank_score))
        enriched = dict(cand)
        enriched["rerank_score"] = rerank_score
        enriched["rerank_fusion_score"] = combined
        weighted.append(enriched)
    weighted.sort(key=lambda c: (c.get("rerank_fusion_score", 1.0), c.get("distance", 1.0)))
    return weighted + suffix


def _expand_hit_contexts(collection, hits: list[dict], window: int, max_chars: int, fallback_kb_id: int | None) -> list[dict]:
    """把最终命中的 chunk 扩展为同文件相邻 chunk 上下文。

    只按 hit 自身的 kb_id（或单库 fallback_kb_id）扩展，避免同名文件跨库串入导致泄露。
    """
    if window <= 0:
        return hits

    expanded_hits = []
    cache: dict[tuple, dict[int, str]] = {}
    for hit in hits:
        filename = hit.get("filename", "")
        chunk_index = hit.get("chunk_index", -1)
        hit_kb_id = hit.get("kb_id", fallback_kb_id)
        if not filename or hit_kb_id is None or chunk_index is None or chunk_index < 0:
            expanded_hits.append(hit)
            continue

        key = (hit_kb_id, filename)
        if key not in cache:
            result = collection.get(
                where={"$and": [{"kb_id": hit_kb_id}, {"filename": filename}]},
                include=["documents", "metadatas"],
            )
            chunks: dict[int, str] = {}
            for doc, metadata in zip(result.get("documents") or [], result.get("metadatas") or []):
                meta = metadata or {}
                idx = meta.get("chunk_index")
                if isinstance(idx, int):
                    chunks[idx] = doc or ""
            cache[key] = chunks

        chunks = cache[key]
        indexes = [i for i in range(chunk_index - window, chunk_index + window + 1) if i in chunks]
        if not indexes:
            expanded_hits.append(hit)
            continue
        parts = [chunks[i] for i in indexes if chunks.get(i)]
        content = "\n".join(parts).strip()
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars]
        enriched = dict(hit)
        enriched["content"] = content or hit.get("content", "")
        enriched["expanded_from"] = chunk_index
        enriched["expanded_chunk_indexes"] = indexes
        expanded_hits.append(enriched)
    return expanded_hits


def delete_document(filename: str, kb_id: int) -> None:
    """删除指定知识库下某个文档的所有片段。"""
    collection = get_collection()
    collection.delete(where={"$and": [{"kb_id": kb_id}, {"filename": filename}]})


def rechunk_docx_documents(kb_id: int, scope_dir: str) -> dict:
    """按当前 DOCX 解析与段落切分策略重建某知识库下的存量 Word 文档。

    只处理 scope_dir 根目录下的 .docx 文件。每个文件先删除旧向量片段，再重新解析、切分、
    embedding 并 upsert，避免旧切分策略留下的 chunk_index 残留。单文件失败不影响整批，
    失败原因回写到元数据，便于前端展示与后续排查。
    """
    from pathlib import Path
    from app.services.document_service import create_document_from_file
    from app.services import metadata_service

    directory = Path(scope_dir)
    if not directory.exists():
        return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0, "files": []}

    files = [p for p in sorted(directory.iterdir()) if p.is_file()]
    docx_files = [p for p in files if p.suffix.lower() == ".docx"]
    results = []
    succeeded = 0
    failed = 0

    for path in docx_files:
        filename = path.name
        try:
            delete_document(filename, kb_id=kb_id)
            document = create_document_from_file(document_id=0, file_path=str(path))
            ingest_result = ingest_document(document, kb_id=kb_id)
            chunk_count = int(ingest_result.get("chunk_count") or 0)
            if chunk_count == 0:
                raise ValueError("文档内容为空或无法提取有效文本，未入库")
            metadata_service.upsert(
                kb_id=kb_id,
                filename=filename,
                status="就绪",
                chunk_count=chunk_count,
                error="",
            )
            results.append({"filename": filename, "status": "success", "chunk_count": chunk_count, "error": ""})
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 —— 单文件失败要继续处理后续文件
            try:
                metadata_service.upsert(
                    kb_id=kb_id,
                    filename=filename,
                    status="失败",
                    chunk_count=0,
                    error=f"DOCX 重切分失败：{exc}",
                )
            except Exception:
                pass
            results.append({"filename": filename, "status": "failed", "chunk_count": 0, "error": str(exc)})
            failed += 1

    return {
        "processed": len(docx_files),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": len(files) - len(docx_files),
        "files": results,
    }


def delete_kb(kb_id: int) -> int:
    """删除某个知识库的全部向量片段（删库时级联）。返回删除前该库的片段数。"""
    collection = get_collection()
    before = collection.get(where={"kb_id": kb_id}, include=[])
    removed = len(before.get("ids") or [])
    if removed:
        collection.delete(where={"kb_id": kb_id})
    return removed


def reconcile(kb_id: int, scope_dir: str) -> dict:
    """对账修复：清理指定知识库里"文件已不存在、但向量仍残留"的僵尸片段。

    做法：把该 kb 在向量库里出现过的 filename，和它的文件目录 scope_dir 里实际存在的
    文件名比对，对每个"向量在、文件不在"的 filename 执行删除（带 kb_id 限定），返回清理详情。
    """
    from pathlib import Path
    from app.services.document_service import SUPPORTED_EXTENSIONS

    collection = get_collection()

    # 只取该知识库的片段
    result = collection.get(where={"kb_id": kb_id}, include=["metadatas"])
    metadatas = result.get("metadatas") or []
    total_before = len(result.get("ids") or [])
    if total_before == 0:
        return {"removed_files": [], "removed_chunks": 0,
                "total_before": 0, "total_after": 0}

    chunk_counts: dict[str, int] = {}
    for metadata in metadatas:
        name = (metadata or {}).get("filename", "")
        if name:
            chunk_counts[name] = chunk_counts.get(name, 0) + 1

    directory = Path(scope_dir)
    existing = set()
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                existing.add(path.name)

    removed_files = []
    removed_chunks = 0
    for name, cnt in chunk_counts.items():
        if name not in existing:
            collection.delete(where={"$and": [{"kb_id": kb_id}, {"filename": name}]})
            removed_files.append({"filename": name, "chunk_count": cnt})
            removed_chunks += cnt

    total_after = len(collection.get(where={"kb_id": kb_id}, include=[]).get("ids") or [])
    return {
        "removed_files": removed_files,
        "removed_chunks": removed_chunks,
        "total_before": total_before,
        "total_after": total_after,
    }


def count(kb_id: int | None = None) -> int:
    """片段数：kb_id 非空时为该库片段数，否则为全库总数。"""
    collection = get_collection()
    if kb_id is None:
        return collection.count()
    return len(collection.get(where={"kb_id": kb_id}, include=[]).get("ids") or [])


def reload_collection(kb_id: int | None = None) -> dict:
    """重新连接向量库，加载磁盘上的最新数据。

    进程启动后 _client/_collection 会一直复用；当向量库在进程外被改动
    （例如用脚本重新入库）时，运行中的进程仍attach着旧句柄、检索不到新数据。
    调用本函数丢弃缓存并重连，即可在不重启后端的情况下拿到最新知识库。

    total_chunks：kb_id 非空时只报该知识库的片段数（避免泄露全局规模）；
    为 None 时报全库总数（管理员场景）。
    """
    global _client, _collection
    _collection = None
    _client = None
    total = count(kb_id)
    return {"reloaded": True, "total_chunks": total}


def stats(kb_id: int | None = None) -> dict:
    """知识库聚合统计，供前端概览图表使用。

    kb_id 非空时只统计该库；为 None 时统计全库（管理员概览）。

    返回：
    - total_chunks：片段总数
    - document_count：不同文件的数量
    - per_document：每个文件的片段数（[{filename, chunk_count}, ...]，按片段数降序）
    """
    collection = get_collection()

    if kb_id is None:
        total = collection.count()
        if total == 0:
            return {"total_chunks": 0, "document_count": 0, "per_document": []}
        result = collection.get(include=["metadatas"])
    else:
        result = collection.get(where={"kb_id": kb_id}, include=["metadatas"])
        total = len(result.get("ids") or [])
        if total == 0:
            return {"total_chunks": 0, "document_count": 0, "per_document": []}

    metadatas = result.get("metadatas") or []

    counts: dict[str, int] = {}
    for metadata in metadatas:
        filename = (metadata or {}).get("filename", "")
        if not filename:
            continue
        counts[filename] = counts.get(filename, 0) + 1

    per_document = [
        {"filename": name, "chunk_count": n}
        for name, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "total_chunks": total,
        "document_count": len(counts),
        "per_document": per_document,
    }


def _set_collection_for_test(collection, client=None) -> None:
    """仅供测试使用：注入一个临时的（内存）集合，替换真实档案柜。

    这样测试就不会碰到硬盘上的真实知识库，也不用调用真实付费接口。

    client：可选，注入集合对应的**公共** chromadb 客户端（EphemeralClient 返回值）。
    检索召回经 langchain_chroma 需要公共 client；测试若未显式传入，则从 collection 的
    底层 server 重建一个等价公共 Client（仅测试环境使用，指向同一份内存数据）。
    """
    global _collection, _client
    _collection = collection
    if client is not None:
        _client = client
    else:
        # 未显式传 client：从注入集合重建一个公共 Client（指向同一底层内存数据）。
        # collection._client 是私有 RustBindingsAPI，langchain 不能直接用；这里把它包成
        # 公共 Client（复用其 _server），仅供测试的检索召回路径。
        try:
            from chromadb.api.client import Client

            reconstructed = Client.__new__(Client)
            reconstructed._server = collection._client
            _client = reconstructed
        except Exception:  # noqa: BLE001 —— 重建失败不阻断（个别老测试可能不走 search）
            _client = None


def _reset_collection_for_test() -> None:
    """仅供测试使用：清掉注入的集合，恢复默认。"""
    global _collection, _client
    _collection = None
    _client = None


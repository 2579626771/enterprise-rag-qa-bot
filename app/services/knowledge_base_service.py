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

    # ★检索召回接入 LangChain（阶段1 地基）★
    # 经 langchain_chroma 的 similarity_search_with_score 召回，为后续检索增强（rerank、
    # 多查询等）铺地基。similarity_search_with_score 返回的 score 即 Chroma 原始余弦距离
    # （已实测与原生 collection.query 的 distance 逐位一致，无换算），distance 语义不漂移。
    # embed_query 由 AliyunEmbeddings 委托 create_query_embedding，与原路径完全等价。
    from app.services.langchain_adapters import build_chroma_vectorstore

    vectorstore = build_chroma_vectorstore(_get_public_client(), collection.name)

    # ★多查询改写（multi-query，阶段4）★
    # 从召回侧补强 Recall：把原问题改写成若干语义等价、措辞不同的查询，原查询 + 改写各自
    # 召回 candidate_k 条，按 (filename, chunk_index) 去重、保留最小 distance（离得最近的那次
    # 命中）。所有查询共用同一个 where 过滤——范围不变，隔离红线不受影响。原查询始终保底参与，
    # 改写只做补充。MULTI_QUERY_ENABLED=false 时只用原查询，行为与阶段1/3 完全一致。
    # 改写失败会自动降级为空列表（只用原查询），绝不中断检索。
    from app.config import MULTI_QUERY_ENABLED, MULTI_QUERY_COUNT

    queries = [question]
    if MULTI_QUERY_ENABLED:
        from app.services import query_rewrite_service

        rewrites = query_rewrite_service.rewrite(question, n=MULTI_QUERY_COUNT)
        queries.extend(rewrites)

    # 多路召回合并：key=(filename, chunk_index)，值取「最小 distance」的那条候选。
    merged: dict[tuple, dict] = {}
    for q in queries:
        scored = vectorstore.similarity_search_with_score(q, k=candidate_k, filter=where)
        for doc, distance in scored:
            metadata = doc.metadata or {}
            key = (metadata.get("filename", ""), metadata.get("chunk_index", -1))
            cand = {
                "content": doc.page_content,
                "filename": metadata.get("filename", ""),
                "chunk_index": metadata.get("chunk_index", -1),
                "distance": distance,
            }
            # 同一片段被多条查询召回时，保留距离最小（最相关）的那次，避免重复且不丢最优分。
            if key not in merged or distance < merged[key]["distance"]:
                merged[key] = cand

    # 按 distance 升序，得到与「单查询召回」同构的候选列表（下游 rerank/过滤逻辑完全复用）。
    candidates = sorted(merged.values(), key=lambda c: c["distance"])

    # ★检索重排（rerank，阶段3）★
    # 双塔向量召回是「粗排」（按余弦距离），交叉编码器 rerank 是「精排」——对 query 与每条
    # 候选逐对打分，更能拉开相关/不相关的分差、修 hard case 漏召回。这里仅用 rerank 分数
    # 「重新排序 candidates」，每条的向量 distance 字段原样保留（阈值过滤仍用它，
    # RAG_MAX_DISTANCE 与答案层研判语义均不受影响）。RERANK_ENABLED=false 时保持距离原序，
    # 行为与阶段1 完全一致。rerank 内部失败会自动降级为原顺序，绝不中断检索。
    from app.config import RERANK_ENABLED

    if RERANK_ENABLED and candidates:
        from app.services import rerank_service

        order = rerank_service.rerank(
            question, [c["content"] for c in candidates], top_n=len(candidates)
        )
        ranked_idx = [o["index"] for o in order]
        # 按 rerank 次序重排；防御性地把未在返回中的候选（异常降级/越界时）追加到末尾，保证不丢。
        seen = set(ranked_idx)
        reordered = [candidates[i] for i in ranked_idx]
        reordered.extend(candidates[i] for i in range(len(candidates)) if i not in seen)
        candidates = reordered

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

    return hits


def delete_document(filename: str, kb_id: int) -> None:
    """删除指定知识库下某个文档的所有片段。"""
    collection = get_collection()
    collection.delete(where={"$and": [{"kb_id": kb_id}, {"filename": filename}]})


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


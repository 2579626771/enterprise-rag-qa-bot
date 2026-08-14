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

    query_vector = create_query_embedding(question)

    # 多召回候选（top_k 的若干倍），给"过滤碎片"留出补位空间。
    candidate_k = min(max(top_k * 4, top_k), total)

    query_kwargs = {
        "query_embeddings": [query_vector],
        "n_results": candidate_k,
    }
    # 范围过滤：kb_ids（多库）优先于 kb_id（单库）；都为 None 则不过滤（全库）。
    if kb_ids is not None:
        query_kwargs["where"] = {"kb_id": {"$in": kb_ids}}
    elif kb_id is not None:
        query_kwargs["where"] = {"kb_id": kb_id}

    result = collection.query(**query_kwargs)

    ids = result["ids"][0]
    documents_text = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    candidates = []
    for i in range(len(ids)):
        metadata = metadatas[i] or {}
        candidates.append(
            {
                "content": documents_text[i],
                "filename": metadata.get("filename", ""),
                "chunk_index": metadata.get("chunk_index", -1),
                "distance": distances[i],
            }
        )

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


def _set_collection_for_test(collection) -> None:
    """仅供测试使用：注入一个临时的（内存）集合，替换真实档案柜。

    这样测试就不会碰到硬盘上的真实知识库，也不用调用真实付费接口。
    """
    global _collection
    _collection = collection


def _reset_collection_for_test() -> None:
    """仅供测试使用：清掉注入的集合，恢复默认。"""
    global _collection, _client
    _collection = None
    _client = None


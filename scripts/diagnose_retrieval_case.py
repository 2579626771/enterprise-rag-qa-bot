"""指定评测题的检索入库形态诊断工具。

用途：排查 #8/#55 这类“检索没命中”到底是召回问题、切分问题，还是评测口径问题。

示例：
    python -m scripts.diagnose_retrieval_case --ids 8,55 --top-k 10
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services import knowledge_base_service  # noqa: E402

QA_PATH = BASE_DIR / "eval" / "qa_set.json"

_KEYWORD_ALIASES = {
    "5分钟": ["5分钟", "5 分钟", "五分钟"],
}


def _aliases(keyword: str) -> list[str]:
    return _KEYWORD_ALIASES.get(keyword, [keyword])


def _matched_keywords(content: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if any(alias in content for alias in _aliases(kw))]


def _parse_ids(raw: str) -> list[int]:
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    return ids


def _all_chunks(kb_id: int, filename: str | None = None) -> list[dict]:
    collection = knowledge_base_service.get_collection()
    where = {"kb_id": kb_id}
    if filename:
        where = {"$and": [{"kb_id": kb_id}, {"filename": filename}]}
    raw = collection.get(where=where, include=["documents", "metadatas"])
    chunks = []
    for doc_id, doc, meta in zip(raw.get("ids") or [], raw.get("documents") or [], raw.get("metadatas") or []):
        chunks.append({
            "id": doc_id,
            "filename": (meta or {}).get("filename", ""),
            "chunk_index": (meta or {}).get("chunk_index", -1),
            "content": doc or "",
        })
    return sorted(chunks, key=lambda c: (c["filename"], c["chunk_index"]))


def _print_chunk(prefix: str, chunk: dict, keywords: list[str]) -> None:
    matched = _matched_keywords(chunk["content"], keywords)
    text = chunk["content"].replace("\n", " | ")
    print(
        f"{prefix} {chunk['filename']}#{chunk['chunk_index']} "
        f"len={len(chunk['content'])} kw={matched}\n    {text[:700]}"
    )


def diagnose(item: dict, top_k: int, context: int) -> None:
    question = item["question"]
    kb_id = item["kb_id"]
    gold_files = item.get("gold_files", [])
    gold_keywords = item.get("gold_keywords", [])

    print("\n" + "=" * 80)
    print(f"#{item['id']} [{item.get('type', '')}] kb={kb_id} answerable={item.get('answerable')}")
    print(f"Q: {question}")
    print(f"gold_files={gold_files}")
    print(f"gold_keywords={gold_keywords}")

    hits = knowledge_base_service.search(question, top_k=top_k, kb_id=kb_id)
    print("\nTop hits:")
    for i, hit in enumerate(hits, start=1):
        dist = hit.get("distance")
        dist_text = f"{dist:.3f}" if isinstance(dist, (int, float)) else "-"
        matched = _matched_keywords(hit.get("content", ""), gold_keywords)
        text = hit.get("content", "").replace("\n", " | ")
        print(
            f"  {i:>2}. dist={dist_text} {hit.get('filename')}#{hit.get('chunk_index')} "
            f"kw={matched}\n      {text[:500]}"
        )

    if not gold_files:
        return

    print("\nGold file keyword locations:")
    for filename in gold_files:
        chunks = _all_chunks(kb_id, filename)
        by_idx = {c["chunk_index"]: c for c in chunks}
        interesting = []
        for chunk in chunks:
            if _matched_keywords(chunk["content"], gold_keywords):
                interesting.append(chunk)
        if not interesting:
            print(f"  {filename}: 未在入库片段中找到 gold_keywords（可能是评测关键词写法/抽取文本差异）")
            continue
        printed = set()
        for chunk in interesting:
            for idx in range(chunk["chunk_index"] - context, chunk["chunk_index"] + context + 1):
                neighbor = by_idx.get(idx)
                if neighbor and (filename, idx) not in printed:
                    mark = "*" if idx == chunk["chunk_index"] else " "
                    _print_chunk(f"  {mark}", neighbor, gold_keywords)
                    printed.add((filename, idx))


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断指定评测题的检索与入库形态")
    parser.add_argument("--ids", required=True, help="题号，逗号分隔，如 8,55")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--context", type=int, default=1, help="打印 gold chunk 前后多少个邻居")
    args = parser.parse_args()

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    wanted = set(_parse_ids(args.ids))
    items = [it for it in qa["items"] if int(it["id"]) in wanted]
    missing = wanted - {int(it["id"]) for it in items}
    if missing:
        print(f"评测集中找不到题号：{sorted(missing)}")
        sys.exit(1)

    for item in items:
        diagnose(item, top_k=args.top_k, context=args.context)


if __name__ == "__main__":
    main()

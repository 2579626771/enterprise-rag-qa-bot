"""检索质量评测脚本 v2（面向真实问题·含幻觉风险度量）。

背景：为「提升检索准召率」引入 LangChain（混合检索/rerank/多查询）前，必须先有
可量化的评测基线。没有度量，「打磨质量」就是碰运气。v1 基线暴露了真实短板不是
「召回不够」（正例已近满分）而是「该拒答时拒不掉」——主题相关但库里没答案的问题
会召回貌似相关的片段，诱导大模型硬答产生幻觉。故 v2 评测集大幅增加 hard-negative。

评测集字段（eval/qa_set.json v2）：
- answerable=true  正例：库里有答案。看前 k 片段是否命中 gold_files + gold_keywords。
- answerable=false 拒答题：库里没答案（hard-negative 主题相关 / negative 完全无关）。
  检索层的「正确行为」是——最近片段距离应足够远，不该有强相关内容冒充答案。

核心指标：
- 正例：命中率、Recall@k、MRR、平均命中距离。
- 拒答题：正确拒答率（top1 距离 > 拒答阈值），并按 hard-negative / negative 分别看。
- ★幻觉风险率：拒答题中 top1 距离 < 拒答阈值（看起来相关、会诱导硬答）的比例。
  这是最贴近「实际会不会乱答」的度量。
- 距离分布：正例命中距离 vs 拒答题 top1 距离，用于判断「拒答阈值」定在哪最优。

排查辅助：
- --ids 8,55 只跑指定题。
- --show-hits 打印每题 topK 的来源、chunk_index、距离与命中关键词。
- --show-content 进一步打印内容预览。
- 正例结果额外输出 combined_hit：topK 合并内容是否覆盖 gold_keywords，用于诊断 #55
  这类「证据跨相邻 chunk」的问题；主 Hit@K 仍保持原有“单个 chunk 命中”口径。

用法：
    python -m scripts.eval_retrieval
    python -m scripts.eval_retrieval --top-k 10 --reject-threshold 0.45
    python -m scripts.eval_retrieval --ids 8,55 --show-hits --show-content
    python -m scripts.eval_retrieval --verbose --save eval/result_legacy_v2.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services import knowledge_base_service  # noqa: E402

QA_PATH = BASE_DIR / "eval" / "qa_set.json"
DEFAULT_REJECT_THRESHOLD = 0.5  # top1 距离 > 该值 视为「正确判定为不相关/应拒答」

# 评测诊断用的轻量别名：不改变题意，只处理中文/阿拉伯数字、空格等写法差异。
# 例：原文为「五分钟一次」，评测 gold 写「5分钟」。
_KEYWORD_ALIASES = {
    "5分钟": ["5分钟", "5 分钟", "五分钟"],
}


def _aliases(keyword: str) -> list[str]:
    return _KEYWORD_ALIASES.get(keyword, [keyword])


def _keyword_present(content: str, keyword: str) -> bool:
    return any(alias in content for alias in _aliases(keyword))


def _matched_keywords(content: str, gold_keywords: list[str]) -> list[str]:
    return [kw for kw in gold_keywords if _keyword_present(content, kw)]


def _required_keyword_count(gold_keywords: list[str]) -> int:
    return max(1, (len(gold_keywords) + 1) // 2)


def _hit_in_chunk(chunk: dict, gold_files: list[str], gold_keywords: list[str]) -> bool:
    """判断单个检索片段是否命中标注答案：来自 gold_files 且含多数 gold_keywords。"""
    filename = chunk.get("filename", "")
    if gold_files and filename not in gold_files:
        return False
    if not gold_keywords:
        return True
    hit_kw = len(_matched_keywords(chunk.get("content", ""), gold_keywords))
    return hit_kw >= _required_keyword_count(gold_keywords)


def _combined_hit(hits: list[dict], gold_files: list[str], gold_keywords: list[str]) -> tuple[bool, list[str]]:
    """topK 合并证据命中：用于诊断跨 chunk 分散的答案，不替代主 Hit@K。"""
    scoped = [h for h in hits if not gold_files or h.get("filename", "") in gold_files]
    combined = "\n".join(h.get("content", "") for h in scoped)
    matched = _matched_keywords(combined, gold_keywords)
    if not gold_keywords:
        return bool(scoped), matched
    return len(matched) >= _required_keyword_count(gold_keywords), matched


def _hit_details(hits: list[dict], gold_keywords: list[str], include_content: bool) -> list[dict]:
    details = []
    for i, h in enumerate(hits, start=1):
        content = h.get("content", "")
        item = {
            "rank": i,
            "filename": h.get("filename", ""),
            "chunk_index": h.get("chunk_index"),
            "distance": h.get("distance"),
            "matched_keywords": _matched_keywords(content, gold_keywords),
            "content_preview": content.replace("\n", " | ")[:240],
        }
        if include_content:
            item["content"] = content
        details.append(item)
    return details


def _eval_one(item: dict, top_k: int, reject_th: float, *, include_hit_details: bool = False,
              include_content: bool = False) -> dict:
    """评测单题。answerable 决定判分口径。"""
    question = item["question"]
    kb_id = item["kb_id"]
    answerable = item.get("answerable", True)
    hits = knowledge_base_service.search(question, top_k=top_k, kb_id=kb_id)
    top1_dist = hits[0]["distance"] if hits else 1.0

    gold_files = item.get("gold_files", [])
    gold_keywords = item.get("gold_keywords", [])
    details = _hit_details(hits, gold_keywords, include_content) if include_hit_details else None

    if answerable:
        hit_rank, hit_distance = 0, None
        for i, chunk in enumerate(hits):
            if _hit_in_chunk(chunk, gold_files, gold_keywords):
                hit_rank, hit_distance = i + 1, chunk.get("distance")
                break
        combined_ok, combined_keywords = _combined_hit(hits, gold_files, gold_keywords)
        result = {
            "id": item["id"], "type": item.get("type", ""), "answerable": True,
            "question": question, "hit": hit_rank > 0, "hit_rank": hit_rank,
            "hit_distance": hit_distance, "top1_distance": top1_dist,
            "combined_hit": combined_ok, "combined_keywords": combined_keywords,
            "top_files": [h.get("filename", "") for h in hits[:3]],
            "top_chunks": [h.get("chunk_index") for h in hits[:3]],
        }
        if details is not None:
            result["hits"] = details
        return result

    # 拒答题：top1 距离越大越好（说明库里确实没有近似内容）
    correct_reject = top1_dist > reject_th
    result = {
        "id": item["id"], "type": item.get("type", ""), "answerable": False,
        "question": question, "correct_reject": correct_reject,
        "top1_distance": top1_dist,
        "top_files": [h.get("filename", "") for h in hits[:3]],
        "top_chunks": [h.get("chunk_index") for h in hits[:3]],
    }
    if details is not None:
        result["hits"] = details
    return result


def _pct(n, d):
    return (n / d) if d else 0.0


def _parse_ids(raw: str) -> set[int] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


def _print_hit_details(result: dict) -> None:
    print(f"\n#{result['id']} {result['question']}")
    if result["answerable"]:
        mark = f"命中@{result['hit_rank']}" if result["hit"] else "未命中"
        combined = "合并命中" if result.get("combined_hit") else "合并未命中"
        print(f"  {mark}；{combined}；合并关键词={result.get('combined_keywords', [])}")
    else:
        mark = "OK拒答" if result["correct_reject"] else "★误召回"
        print(f"  {mark}；top1距离={result['top1_distance']:.3f}")
    for h in result.get("hits", []):
        d = h.get("distance")
        dist = f"{d:.3f}" if isinstance(d, (int, float)) else "-"
        print(
            f"  {h['rank']:>2}. dist={dist} chunk={h.get('chunk_index')} "
            f"kw={h.get('matched_keywords', [])} file={h.get('filename')}"
        )
        preview = h.get("content") or h.get("content_preview")
        if preview:
            print(f"      {preview.replace(chr(10), ' | ')[:800]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量评测 v2")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--reject-threshold", type=float, default=DEFAULT_REJECT_THRESHOLD,
                        help="top1距离>该值判为应拒答（默认0.5，与config RAG_MAX_DISTANCE一致）")
    parser.add_argument("--ids", type=str, default="", help="只评测指定题号，逗号分隔，如 8,55")
    parser.add_argument("--retrieval-mode", type=str, default="", help="临时覆盖 RETRIEVAL_MODE，如 vector/hybrid/rerank_fusion")
    parser.add_argument("--context-window", type=int, default=None, help="临时覆盖 RETRIEVAL_CONTEXT_WINDOW")
    parser.add_argument("--rerank-strategy", type=str, default="", help="临时覆盖 RERANK_STRATEGY，如 sort/window/weighted")
    parser.add_argument("--show-hits", action="store_true", help="打印每题 topK 命中明细")
    parser.add_argument("--show-content", action="store_true", help="配合 --show-hits 打印更完整内容")
    parser.add_argument("--save", type=str, default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.retrieval_mode or args.context_window is not None or args.rerank_strategy:
        import app.config as config

        if args.retrieval_mode:
            config.RETRIEVAL_MODE = args.retrieval_mode.strip().lower()
        if args.context_window is not None:
            config.RETRIEVAL_CONTEXT_WINDOW = args.context_window
        if args.rerank_strategy:
            config.RERANK_STRATEGY = args.rerank_strategy.strip().lower()

    if not QA_PATH.exists():
        print(f"找不到评测集：{QA_PATH}")
        sys.exit(1)

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    items = qa["items"]
    selected_ids = _parse_ids(args.ids)
    if selected_ids is not None:
        items = [it for it in items if int(it["id"]) in selected_ids]
    th = args.reject_threshold

    t0 = time.time()
    include_details = args.show_hits or bool(args.save)
    results = [
        _eval_one(
            it,
            args.top_k,
            th,
            include_hit_details=include_details,
            include_content=args.show_content,
        )
        for it in items
    ]
    elapsed = time.time() - t0

    if args.verbose:
        for r in results:
            if r["answerable"]:
                mark = f"命中@{r['hit_rank']}" if r["hit"] else "未命中 "
                d = f"{r['hit_distance']:.3f}" if r["hit_distance"] is not None else "  -  "
                combined = "合并命中" if r.get("combined_hit") else "合并未中"
                print(f"[{r['id']:>2}] {mark} | {combined} | 命中距离={d} | {r['question'][:32]}")
            else:
                mark = "OK拒答" if r["correct_reject"] else "★误召回"
                print(f"[{r['id']:>2}] {mark:>6} | top1距离={r['top1_distance']:.3f} | [{r['type']}] {r['question'][:28]}")

    if args.show_hits:
        for r in results:
            _print_hit_details(r)

    # ---- 分组 ----
    pos = [r for r in results if r["answerable"]]
    neg = [r for r in results if not r["answerable"]]
    hard = [r for r in neg if r["type"] == "hard-negative"]
    plain_neg = [r for r in neg if r["type"] == "negative"]

    # 正例指标
    n_pos, n_hit = len(pos), sum(1 for r in pos if r["hit"])
    hit_rate = _pct(n_hit, n_pos)
    mrr = _pct(sum(1.0 / r["hit_rank"] for r in pos if r["hit"]), n_pos)
    combined_hit = sum(1 for r in pos if r.get("combined_hit"))
    combined_rate = _pct(combined_hit, n_pos)
    hit_dists = [r["hit_distance"] for r in pos if r["hit"] and r["hit_distance"] is not None]
    avg_hit_dist = sum(hit_dists) / len(hit_dists) if hit_dists else 0.0

    # 拒答指标
    def reject_stats(group):
        n = len(group)
        ok = sum(1 for r in group if r["correct_reject"])
        return n, ok, _pct(ok, n)

    n_neg, ok_neg, rate_neg = reject_stats(neg)
    n_hard, ok_hard, rate_hard = reject_stats(hard)
    n_pn, ok_pn, rate_pn = reject_stats(plain_neg)
    # 幻觉风险率 = 拒答题里「看起来相关(误召回)」的比例
    halluc_risk = _pct(n_neg - ok_neg, n_neg)

    # 距离分布（用于选阈值）
    neg_dists = sorted(r["top1_distance"] for r in neg)
    hard_dists = sorted(r["top1_distance"] for r in hard)

    print("\n" + "=" * 60)
    scope = f" | ids={args.ids}" if args.ids else ""
    print(f"检索评测 v2 | top_k={args.top_k} | 拒答阈值={th}{scope} | {len(items)}题 | {elapsed:.1f}s")
    print("=" * 60)
    print(f"【正例 {n_pos}题】库里有答案，越高越好")
    print(f"  命中率 Hit@{args.top_k}   : {hit_rate:.1%}  ({n_hit}/{n_pos})")
    print(f"  合并证据命中率    : {combined_rate:.1%}  ({combined_hit}/{n_pos})  ←诊断跨chunk证据，不替代Hit@K")
    print(f"  MRR              : {mrr:.3f}")
    print(f"  平均命中距离     : {avg_hit_dist:.3f}")
    print(f"【拒答 {n_neg}题】库里没答案，正确拒答率越高越好")
    print(f"  总正确拒答率     : {rate_neg:.1%}  ({ok_neg}/{n_neg})")
    print(f"    ├ hard-negative: {rate_hard:.1%}  ({ok_hard}/{n_hard})  ←主题相关的幻觉陷阱")
    print(f"    └ 完全无关     : {rate_pn:.1%}  ({ok_pn}/{n_pn})")
    print(f"  ★幻觉风险率      : {halluc_risk:.1%}  （拒答题里被误当相关、会诱导硬答的比例，越低越好）")
    print("-" * 60)
    print(f"  正例命中距离范围 : {min(hit_dists):.3f} ~ {max(hit_dists):.3f}" if hit_dists else "  正例无命中")
    if hard_dists:
        print(f"  hard-neg距离范围 : {min(hard_dists):.3f} ~ {max(hard_dists):.3f}（中位 {hard_dists[len(hard_dists)//2]:.3f}）")
    print("  → 若两区间重叠严重，说明'距离阈值'无法区分能答/不能答，需靠rerank或答案层兜底")
    print("-" * 60)
    # 未命中正例
    miss = [r for r in pos if not r["hit"]]
    if miss:
        print("  未命中正例（漏召回，优先排查）：")
        for r in miss:
            combined = "；topK合并证据已覆盖" if r.get("combined_hit") else ""
            print(f"    #{r['id']} [{r['type']}] {r['question'][:30]} -> 召回:{r['top_files'][:2]}{combined}")
    # 误召回的拒答题（幻觉高危）
    bad = [r for r in neg if not r["correct_reject"]]
    if bad:
        print("  ★误召回的拒答题（幻觉高危，最该治）：")
        for r in sorted(bad, key=lambda x: x["top1_distance"]):
            print(f"    #{r['id']} [{r['type']}] 距离={r['top1_distance']:.3f} {r['question'][:26]} -> {r['top_files'][:1]}")
    print("=" * 60)

    if args.save:
        out = {
            "top_k": args.top_k, "reject_threshold": th, "ids": sorted(selected_ids) if selected_ids else None,
            "metrics": {
                "pos_hit_rate": hit_rate, "combined_hit_rate": combined_rate,
                "mrr": mrr, "avg_hit_distance": avg_hit_dist,
                "reject_rate_all": rate_neg, "reject_rate_hard": rate_hard,
                "reject_rate_plain": rate_pn, "hallucination_risk": halluc_risk,
                "n_pos": n_pos, "n_hit": n_hit, "n_combined_hit": combined_hit,
                "n_neg": n_neg, "n_hard": n_hard,
            },
            "distance_dist": {
                "pos_hit": hit_dists, "hard_neg": hard_dists, "all_neg": neg_dists,
            },
            "results": results,
        }
        p = Path(args.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已存档：{p}")


if __name__ == "__main__":
    main()

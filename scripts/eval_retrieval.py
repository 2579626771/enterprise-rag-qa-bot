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

用法：
    python -m scripts.eval_retrieval
    python -m scripts.eval_retrieval --top-k 10 --reject-threshold 0.45
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


def _hit_in_chunk(chunk: dict, gold_files: list[str], gold_keywords: list[str]) -> bool:
    """判断单个检索片段是否命中标注答案：来自 gold_files 且含多数 gold_keywords。"""
    filename = chunk.get("filename", "")
    if gold_files and filename not in gold_files:
        return False
    if not gold_keywords:
        return True
    hit_kw = sum(1 for kw in gold_keywords if kw in chunk.get("content", ""))
    return hit_kw >= max(1, (len(gold_keywords) + 1) // 2)


def _eval_one(item: dict, top_k: int, reject_th: float) -> dict:
    """评测单题。answerable 决定判分口径。"""
    question = item["question"]
    kb_id = item["kb_id"]
    answerable = item.get("answerable", True)
    hits = knowledge_base_service.search(question, top_k=top_k, kb_id=kb_id)
    top1_dist = hits[0]["distance"] if hits else 1.0

    if answerable:
        gold_files = item.get("gold_files", [])
        gold_keywords = item.get("gold_keywords", [])
        hit_rank, hit_distance = 0, None
        for i, chunk in enumerate(hits):
            if _hit_in_chunk(chunk, gold_files, gold_keywords):
                hit_rank, hit_distance = i + 1, chunk.get("distance")
                break
        return {
            "id": item["id"], "type": item.get("type", ""), "answerable": True,
            "question": question, "hit": hit_rank > 0, "hit_rank": hit_rank,
            "hit_distance": hit_distance, "top1_distance": top1_dist,
            "top_files": [h.get("filename", "") for h in hits[:3]],
        }

    # 拒答题：top1 距离越大越好（说明库里确实没有近似内容）
    correct_reject = top1_dist > reject_th
    return {
        "id": item["id"], "type": item.get("type", ""), "answerable": False,
        "question": question, "correct_reject": correct_reject,
        "top1_distance": top1_dist,
        "top_files": [h.get("filename", "") for h in hits[:3]],
    }


def _pct(n, d):
    return (n / d) if d else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量评测 v2")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--reject-threshold", type=float, default=DEFAULT_REJECT_THRESHOLD,
                        help="top1距离>该值判为应拒答（默认0.5，与config RAG_MAX_DISTANCE一致）")
    parser.add_argument("--save", type=str, default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not QA_PATH.exists():
        print(f"找不到评测集：{QA_PATH}")
        sys.exit(1)

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    items = qa["items"]
    th = args.reject_threshold

    t0 = time.time()
    results = [_eval_one(it, args.top_k, th) for it in items]
    elapsed = time.time() - t0

    if args.verbose:
        for r in results:
            if r["answerable"]:
                mark = f"命中@{r['hit_rank']}" if r["hit"] else "未命中 "
                d = f"{r['hit_distance']:.3f}" if r["hit_distance"] is not None else "  -  "
                print(f"[{r['id']:>2}] {mark} | 命中距离={d} | {r['question'][:32]}")
            else:
                mark = "OK拒答" if r["correct_reject"] else "★误召回"
                print(f"[{r['id']:>2}] {mark:>6} | top1距离={r['top1_distance']:.3f} | [{r['type']}] {r['question'][:28]}")

    # ---- 分组 ----
    pos = [r for r in results if r["answerable"]]
    neg = [r for r in results if not r["answerable"]]
    hard = [r for r in neg if r["type"] == "hard-negative"]
    plain_neg = [r for r in neg if r["type"] == "negative"]

    # 正例指标
    n_pos, n_hit = len(pos), sum(1 for r in pos if r["hit"])
    hit_rate = _pct(n_hit, n_pos)
    mrr = _pct(sum(1.0 / r["hit_rank"] for r in pos if r["hit"]), n_pos)
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
    print(f"检索评测 v2 | top_k={args.top_k} | 拒答阈值={th} | {len(items)}题 | {elapsed:.1f}s")
    print("=" * 60)
    print(f"【正例 {n_pos}题】库里有答案，越高越好")
    print(f"  命中率 Hit@{args.top_k}   : {hit_rate:.1%}  ({n_hit}/{n_pos})")
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
            print(f"    #{r['id']} [{r['type']}] {r['question'][:30]} -> 召回:{r['top_files'][:2]}")
    # 误召回的拒答题（幻觉高危）
    bad = [r for r in neg if not r["correct_reject"]]
    if bad:
        print("  ★误召回的拒答题（幻觉高危，最该治）：")
        for r in sorted(bad, key=lambda x: x["top1_distance"]):
            print(f"    #{r['id']} [{r['type']}] 距离={r['top1_distance']:.3f} {r['question'][:26]} -> {r['top_files'][:1]}")
    print("=" * 60)

    if args.save:
        out = {
            "top_k": args.top_k, "reject_threshold": th,
            "metrics": {
                "pos_hit_rate": hit_rate, "mrr": mrr, "avg_hit_distance": avg_hit_dist,
                "reject_rate_all": rate_neg, "reject_rate_hard": rate_hard,
                "reject_rate_plain": rate_pn, "hallucination_risk": halluc_risk,
                "n_pos": n_pos, "n_hit": n_hit, "n_neg": n_neg, "n_hard": n_hard,
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

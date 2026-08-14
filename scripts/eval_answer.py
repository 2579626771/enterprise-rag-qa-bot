"""研判层评测脚本（防幻觉的 before/after 真数字）。

与 eval_retrieval.py 的区别：
- eval_retrieval.py 只测「检索层」——片段有没有召回对，测不到幻觉。
- 本脚本测「完整研判路径」——调 rag_service.answer_from_knowledge_base（JUDGE_ENABLED=true），
  看研判层能否把「主题相关但库里没答案」的问题正确判为不可回答（answerable=false），
  同时不误伤本可回答的正例。这才是防幻觉的直接度量。

核心指标（基于 eval/qa_set.json 的 answerable 标注）：
- 正例（answerable=true）：
    · 保持可回答率 = 判为 answerable=true 的比例（越高越好，过低=误伤/过度拒答）。
- 拒答题（answerable=false，主要是 hard-negative）：
    · 正确拒答率 = 判为 answerable=false 的比例（越高越好；基线 legacy 检索层为 0%）。
- 综合：幻觉风险率 = 拒答题里被判为「可回答」的比例（越低越好）。

⚠️ 本脚本会真实调用 DeepSeek（每题一次），有成本与耗时。默认对全部 62 题跑。
可用 --limit N 先小样本试跑，--types 只跑某几类。

用法（需在 .env 或环境变量设好 DEEPSEEK_API_KEY，且 SSL_CERT_FILE 不指向不存在的文件）：
    python -m scripts.eval_answer --save eval/result_judge_v2.json
    python -m scripts.eval_answer --limit 8 --verbose
    python -m scripts.eval_answer --types hard-negative,fact
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 强制打开研判层（脚本级覆盖配置；不改 .env）。必须在 import rag_service 之前设置，
# 因为 rag_service 在 import 时从 config 快照 JUDGE_ENABLED。
import app.config as config  # noqa: E402
config.JUDGE_ENABLED = True

import app.services.rag_service as rag_service  # noqa: E402
rag_service.JUDGE_ENABLED = True  # 双保险：覆盖 rag_service 的模块级快照

from app.services.rag_service import answer_from_knowledge_base  # noqa: E402

QA_PATH = BASE_DIR / "eval" / "qa_set.json"


def _pct(n, d):
    return (n / d) if d else 0.0


def _eval_one(item: dict) -> dict:
    question = item["question"]
    kb_id = item["kb_id"]
    expected_answerable = item.get("answerable", True)

    t0 = time.time()
    result = answer_from_knowledge_base(question=question, kb_id=kb_id)
    dt = time.time() - t0

    judged_answerable = result.get("answerable", True)
    # 判定正确：研判结论与标注一致
    correct = (judged_answerable == expected_answerable)
    return {
        "id": item["id"], "type": item.get("type", ""),
        "expected_answerable": expected_answerable,
        "judged_answerable": judged_answerable,
        "correct": correct,
        "confidence": result.get("confidence", ""),
        "reason": result.get("reason", "")[:80],
        "question": question,
        "elapsed": dt,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="研判层评测（防幻觉）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全部）")
    parser.add_argument("--types", type=str, default="", help="只跑这些类型，逗号分隔")
    parser.add_argument("--save", type=str, default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not QA_PATH.exists():
        print(f"找不到评测集：{QA_PATH}")
        sys.exit(1)

    items = json.loads(QA_PATH.read_text(encoding="utf-8"))["items"]
    if args.types:
        wanted = {t.strip() for t in args.types.split(",")}
        items = [it for it in items if it.get("type") in wanted]
    if args.limit > 0:
        items = items[: args.limit]

    print(f"研判评测：{len(items)} 题，真实调用 DeepSeek（JUDGE_ENABLED=True）...")
    t0 = time.time()
    results = []
    for it in items:
        r = _eval_one(it)
        results.append(r)
        if args.verbose:
            exp = "可答" if r["expected_answerable"] else "应拒"
            jud = "可答" if r["judged_answerable"] else "拒答"
            mark = "OK" if r["correct"] else "✗ "
            print(f"[{r['id']:>2}] {mark} 期望={exp} 研判={jud} conf={r['confidence']:<4} "
                  f"| {r['question'][:26]} | {r['reason'][:30]}")
    elapsed = time.time() - t0

    pos = [r for r in results if r["expected_answerable"]]
    neg = [r for r in results if not r["expected_answerable"]]
    hard = [r for r in neg if r["type"] == "hard-negative"]
    plain = [r for r in neg if r["type"] == "negative"]

    # 正例：保持可回答率（judged=true 的比例）
    pos_keep = _pct(sum(1 for r in pos if r["judged_answerable"]), len(pos))
    # 拒答题：正确拒答率（judged=false 的比例）
    def refuse_rate(group):
        return _pct(sum(1 for r in group if not r["judged_answerable"]), len(group))
    neg_ref = refuse_rate(neg)
    hard_ref = refuse_rate(hard)
    plain_ref = refuse_rate(plain)
    halluc = _pct(sum(1 for r in neg if r["judged_answerable"]), len(neg))

    print("\n" + "=" * 60)
    print(f"研判层评测结果 | {len(items)}题 | {elapsed:.1f}s | 平均 {elapsed/max(1,len(items)):.1f}s/题")
    print("=" * 60)
    print(f"【正例 {len(pos)}题】库里有答案，应判「可回答」")
    print(f"  保持可回答率     : {pos_keep:.1%}  （过低=误伤正例/过度拒答）")
    print(f"【拒答题 {len(neg)}题】库里没答案，应判「拒答」")
    print(f"  正确拒答率(总)   : {neg_ref:.1%}   ← 基线检索层为 0%")
    print(f"    ├ hard-negative: {hard_ref:.1%}  ({sum(1 for r in hard if not r['judged_answerable'])}/{len(hard)})")
    print(f"    └ 完全无关     : {plain_ref:.1%}  ({sum(1 for r in plain if not r['judged_answerable'])}/{len(plain)})")
    print(f"  ★幻觉风险率      : {halluc:.1%}   ← 基线 91.7%，越低越好")
    print("-" * 60)
    # 错判清单
    wrong_pos = [r for r in pos if not r["judged_answerable"]]
    if wrong_pos:
        print(f"  过度拒答的正例（误伤，{len(wrong_pos)}）：")
        for r in wrong_pos:
            print(f"    #{r['id']} [{r['type']}] {r['question'][:30]} | {r['reason'][:30]}")
    wrong_neg = [r for r in neg if r["judged_answerable"]]
    if wrong_neg:
        print(f"  漏拒的拒答题（仍有幻觉风险，{len(wrong_neg)}）：")
        for r in wrong_neg:
            print(f"    #{r['id']} [{r['type']}] {r['question'][:30]} | conf={r['confidence']}")
    print("=" * 60)

    if args.save:
        out = {
            "n": len(items),
            "metrics": {
                "pos_keep_rate": pos_keep, "reject_rate_all": neg_ref,
                "reject_rate_hard": hard_ref, "reject_rate_plain": plain_ref,
                "hallucination_risk": halluc,
                "n_pos": len(pos), "n_neg": len(neg), "n_hard": len(hard),
            },
            "results": results,
        }
        p = Path(args.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已存档：{p}")


if __name__ == "__main__":
    main()

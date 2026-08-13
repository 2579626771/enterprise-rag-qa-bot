"""为存量知识库回填默认主题分类 —— 一次性脚本。

背景：主题分类从「全局字典」改为「按知识库隔离」后，新建知识库会自动种入 8 个
默认分类；但升级前已存在的知识库还没有任何分类。本脚本给这些库补种默认分类。

做法：遍历所有知识库，对「尚无任何分类」的库调用 topic_service.seed_defaults(kb_id)。
已有分类的库不动（幂等，不覆盖用户已改动的分类）。

用法：
    python -m scripts.seed_kb_topics          # 交互确认后执行
    python -m scripts.seed_kb_topics --yes    # 跳过确认

依赖服务层自身的 MySQL/内存降级逻辑；MYSQL_ENABLED=false 时对内存仓库无实际意义
（重启即失），脚本会提示。
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import MYSQL_ENABLED  # noqa: E402
from app.services import kb_service, topic_service  # noqa: E402


def main() -> None:
    skip_confirm = "--yes" in sys.argv

    if not MYSQL_ENABLED:
        print("MYSQL_ENABLED=false：当前为内存仓库，回填对持久化无意义（重启即失）。")

    kbs = kb_service.list_all()
    print("=" * 60)
    print(f"将检查 {len(kbs)} 个知识库，对尚无分类的库种入默认分类：")
    for kb in kbs:
        print(f"  - kb #{kb['id']} 「{kb['name']}」")
    print("=" * 60)
    print("已有分类的库不受影响（幂等）。")

    if not skip_confirm:
        ans = input("确认执行？输入 yes 继续：").strip().lower()
        if ans != "yes":
            print("已取消。")
            return

    seeded = 0
    skipped = 0
    for kb in kbs:
        kb_id = kb["id"]
        existing = topic_service.list_topics(kb_id)
        if existing:
            skipped += 1
            print(f"- kb #{kb_id} 已有 {len(existing)} 个分类，跳过。")
            continue
        topic_service.seed_defaults(kb_id)
        seeded += 1
        print(f"- kb #{kb_id} 已种入 {len(topic_service.DEFAULT_TOPICS)} 个默认分类。")

    print(f"完成：{seeded} 个库已回填，{skipped} 个库已有分类跳过。")


if __name__ == "__main__":
    main()

"""【已废弃 · 请勿运行】把旧的 data/documents/{kb_id}/ 目录搬到
data/documents/{用户名}/{知识库名}_{kb_id}/ 层级结构。

⚠ 弃用说明（2026-08）：
    本脚本产生的「{用户名}/{库名}_{kb_id}/」命名，因目录名内嵌库名，导致
    「知识库改名后按新名找不到旧目录、文档消失」的严重问题。现已改为末层只用
    kb_id 的方案（{用户名}/{kb_id}/，见 document_service.kb_documents_dir）。
    请改用 scripts/migrate_kbid_dirs.py 迁移，切勿再运行本脚本，否则会把目录
    退回到有 bug 的「带库名」结构。保留此文件仅作历史记录。

一次性迁移：把旧的 data/documents/{kb_id}/ 目录搬到新的
data/documents/{用户名}/{知识库名}_{kb_id}/ 层级结构。

背景：多知识库改造早期，文件按 kb_id 平铺存放（如 6/ 7/ 8/ 13/），人工查看时
认不出归属。现改为「用户名/库名_kbid」两级目录（见 document_service.kb_documents_dir）。
本脚本把磁盘上已有的旧目录搬到新位置，与新代码对齐。

用法：
    python -m scripts.migrate_doc_dirs          # 交互确认后执行
    python -m scripts.migrate_doc_dirs --yes    # 跳过确认

特性：
- 只处理「纯数字」子目录（旧的 kb_id 目录）；已在新结构下的不动（幂等）。
- 查不到对应知识库的孤儿目录 → 跳过并告警，不删除。
- 目标已存在同名目录 → 跳过并告警，避免覆盖。
"""

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import DOCUMENTS_DIR  # noqa: E402
from app.services import kb_service, user_service  # noqa: E402
from app.services.document_service import _sanitize_path_segment  # noqa: E402


def _plan_moves():
    """返回 [(旧目录, 新目录, 说明)] 列表。"""
    base = Path(DOCUMENTS_DIR)
    moves = []
    if not base.exists():
        return moves

    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        # 只认「纯数字」目录 = 旧 kb_id 目录
        if not entry.name.isdigit():
            continue
        kb_id = int(entry.name)
        kb = kb_service.get(kb_id)
        if not kb:
            moves.append((entry, None, f"孤儿目录（DB 无 kb {kb_id}），跳过"))
            continue
        owner = user_service.get_by_id(kb["owner_id"])
        username = owner["username"] if owner else f"user{kb['owner_id']}"
        new_dir = (
            base
            / _sanitize_path_segment(username, fallback=f"user{kb['owner_id']}")
            / f"{_sanitize_path_segment(kb['name'], fallback='kb')}_{kb_id}"
        )
        moves.append((entry, new_dir, f"kb {kb_id}「{kb['name']}」→ {username}"))
    return moves


def main() -> None:
    # 运行时护栏：此脚本已废弃（会把目录退回到「带库名」的有 bug 结构）。
    # 必须显式传 --force-deprecated 才会执行，防止误运行。
    if "--force-deprecated" not in sys.argv:
        print("[已废弃] 本脚本会把目录退回到「{用户名}/{库名}_{kb_id}」的有 bug 结构，已停用。")
        print("请改用：python -m scripts.migrate_kbid_dirs --apply")
        print("（如确需运行历史逻辑，加 --force-deprecated 强制执行，风险自负）")
        return

    skip_confirm = "--yes" in sys.argv
    moves = _plan_moves()

    if not moves:
        print("没有需要迁移的旧目录（data/documents 下无纯数字子目录）。")
        return

    print("=" * 60)
    print("将执行以下目录迁移：")
    for old, new, note in moves:
        if new is None:
            print(f"  [跳过] {old.name}/  —— {note}")
        else:
            rel_new = new.relative_to(Path(DOCUMENTS_DIR))
            print(f"  {old.name}/  ->  {rel_new}/   （{note}）")
    print("=" * 60)

    if not skip_confirm:
        ans = input("确认执行？输入 yes 继续：").strip().lower()
        if ans != "yes":
            print("已取消。")
            return

    moved = skipped = 0
    for old, new, note in moves:
        if new is None:
            skipped += 1
            continue
        if new.exists():
            # 目标已存在：若为空则把旧目录里的文件搬进去（合并），非空则跳过避免覆盖。
            if any(new.iterdir()):
                print(f"  [跳过] 目标非空：{new.relative_to(Path(DOCUMENTS_DIR))}")
                skipped += 1
                continue
            files = [f for f in old.iterdir() if f.is_file()]
            for f in files:
                shutil.move(str(f), str(new / f.name))
            # 旧目录若已空则删掉
            try:
                if not any(old.iterdir()):
                    old.rmdir()
            except OSError:
                pass
            moved += 1
            print(f"  [合并] {old.name}/ 的 {len(files)} 个文件 -> {new.relative_to(Path(DOCUMENTS_DIR))}/")
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
        moved += 1
        print(f"  [完成] {old.name}/ -> {new.relative_to(Path(DOCUMENTS_DIR))}/")

    print(f"\n迁移完成：搬移 {moved} 个，跳过 {skipped} 个。")


if __name__ == "__main__":
    main()

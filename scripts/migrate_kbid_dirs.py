"""一次性迁移（B1 方案）：把文档目录统一为 DOCUMENTS_DIR/{用户名}/{kb_id}/。

背景：此前目录名含库名（{用户名}/{库名}_{kb_id}/），知识库改名后 DB 名字变了、
磁盘目录名没变，导致新代码按新名去找、读到空目录，文档「消失」。B1 方案让末层
只用 kb_id，改名不再影响路径。本脚本把磁盘上已有的各种历史结构统一迁到新命名：

  {用户名}/{库名}_{kb_id}/   ->  {用户名}/{kb_id}/     （去掉库名段）
  {kb_id}/ （最早期平铺）      ->  {用户名}/{kb_id}/     （补上用户名层）

同一个 kb 若存在多个来源目录（如改名产生的「旧名目录 + 新名空目录」），全部
合并进目标 {用户名}/{kb_id}/，文件不覆盖（重名自动加 _dup 后缀），零丢失。

用法：
    python -m scripts.migrate_kbid_dirs          # 预演（dry-run），只打印不改动
    python -m scripts.migrate_kbid_dirs --apply  # 真正执行
"""

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import DOCUMENTS_DIR  # noqa: E402
from app.services import kb_service, user_service  # noqa: E402
from app.services.document_service import _sanitize_path_segment  # noqa: E402

SUPPORTED = {".txt", ".md", ".pdf", ".docx"}


def _files_in(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [f for f in directory.iterdir() if f.is_file()]


def _plan():
    """返回 [(kb_id, username, target, [源目录...])]，target 为最终 {用户名}/{kb_id}/。"""
    base = Path(DOCUMENTS_DIR)
    plan = []
    for kb in kb_service.list_all():
        kb_id = kb["id"]
        owner = user_service.get_by_id(kb["owner_id"])
        username = owner["username"] if owner else f"user{kb['owner_id']}"
        user_seg = _sanitize_path_segment(username, fallback=f"user{kb['owner_id']}")
        user_dir = base / user_seg
        target = user_dir / str(kb_id)

        sources = []
        # 1) {用户名}/ 下所有以 _{kb_id} 结尾的旧库名目录
        if user_dir.exists():
            for d in sorted(user_dir.iterdir()):
                if d.is_dir() and d.name.endswith(f"_{kb_id}") and d.resolve() != target.resolve():
                    sources.append(d)
        # 2) 最早期平铺的 {kb_id}/ 目录
        legacy = base / str(kb_id)
        if legacy.exists() and legacy.is_dir() and legacy.resolve() != target.resolve():
            sources.append(legacy)

        # 只保留「有文件」的源，避免空目录噪音
        sources = [s for s in sources if _files_in(s)]
        if sources:
            plan.append((kb_id, username, target, sources))
    return plan


def _unique_dest(target: Path, name: str) -> Path:
    """目标目录内若已存在同名文件，追加 _dup/_dup2… 避免覆盖。"""
    dest = target / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        cand = target / f"{stem}_dup{'' if i == 1 else i}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def main() -> None:
    apply = "--apply" in sys.argv
    base = Path(DOCUMENTS_DIR)
    plan = _plan()

    print("=" * 72)
    print(f"文档根目录：{base}")
    print(f"模式：{'APPLY（真正执行）' if apply else 'DRY-RUN（仅预演，不改动）'}")
    print("=" * 72)

    if not plan:
        print("\n[OK] 没有需要迁移的目录，磁盘结构已是 {用户名}/{kb_id}/。")
        return

    total_files = 0
    for kb_id, username, target, sources in plan:
        print(f"\n* kb_id={kb_id}  属主 {username}  ->  目标 {target.relative_to(base)}/")
        for s in sources:
            files = _files_in(s)
            total_files += len(files)
            print(f"    从 {s.relative_to(base)}/  搬 {len(files)} 个文件")
            if not apply:
                continue
            target.mkdir(parents=True, exist_ok=True)
            for f in files:
                dest = _unique_dest(target, f.name)
                if dest.name != f.name:
                    print(f"      [!] 目标已存在同名，改存为 {dest.name}")
                shutil.move(str(f), str(dest))
            # 源目录若已空则清理
            try:
                if not any(s.iterdir()):
                    s.rmdir()
            except OSError:
                pass

    print("\n" + "=" * 72)
    if apply:
        print(f"[DONE] 迁移完成，共搬移 {total_files} 个文件。")
        print("建议随后运行：python -m scripts.diagnose_doc_dirs  验证无失配。")
    else:
        print(f"[DRY-RUN] 以上为预演，未改动任何文件（共将搬移 {total_files} 个）。")
        print("确认无误后加 --apply 真正执行：python -m scripts.migrate_kbid_dirs --apply")


if __name__ == "__main__":
    main()

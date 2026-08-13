"""只读诊断：检查每个知识库的文档目录是否与「当前库名」失配。

背景：kb_documents_dir() 用「用户名/{库名}_{kb_id}」拼路径。知识库改名后，
DB 里的 name 变了，但磁盘目录名仍是旧库名 → 程序按新名去找 → 读到空目录 →
文档「消失」。本脚本只读不改，列出所有失配项与文件数，供人工确认。

用法：
    python -m scripts.diagnose_doc_dirs
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import DOCUMENTS_DIR  # noqa: E402
from app.services import kb_service, user_service  # noqa: E402
from app.services.document_service import _sanitize_path_segment  # noqa: E402

SUPPORTED = {".txt", ".md", ".pdf", ".docx"}


def _count_docs(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for f in directory.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED)


def main() -> None:
    base = Path(DOCUMENTS_DIR)
    kbs = kb_service.list_all()
    print("=" * 72)
    print(f"文档根目录：{base}")
    print(f"知识库总数（DB）：{len(kbs)}")
    print("=" * 72)

    mismatched = []
    for kb in kbs:
        kb_id = kb["id"]
        owner = user_service.get_by_id(kb["owner_id"])
        username = owner["username"] if owner else f"user{kb['owner_id']}"
        user_dir = base / _sanitize_path_segment(username, fallback=f"user{kb['owner_id']}")

        # 期望目录（新代码会去读的）
        expected = user_dir / f"{_sanitize_path_segment(kb['name'], fallback='kb')}_{kb_id}"
        expected_n = _count_docs(expected)

        # 磁盘上所有以 _{kb_id} 结尾的目录（可能含旧库名目录）
        actual_dirs = []
        if user_dir.exists():
            for d in sorted(user_dir.iterdir()):
                if d.is_dir() and d.name.endswith(f"_{kb_id}"):
                    actual_dirs.append((d, _count_docs(d)))
        # 也检查纯数字 kb_id 目录（更早期结构，可能仍有残留）
        legacy = base / str(kb_id)
        if legacy.exists() and legacy.is_dir():
            actual_dirs.append((legacy, _count_docs(legacy)))

        # 失配判定：存在「非期望目录」且里面有文件，或期望目录为空但别处有文件
        stray = [(d, n) for (d, n) in actual_dirs if d.resolve() != expected.resolve() and n > 0]
        if stray:
            mismatched.append((kb, username, expected, expected_n, stray))

    if not mismatched:
        print("\n[OK] 未发现失配：所有知识库的文档都在「当前库名对应目录」里。")
        return

    print(f"\n[!!] 发现 {len(mismatched)} 个失配的知识库（文档在旧目录里、当前库读不到）：\n")
    for kb, username, expected, expected_n, stray in mismatched:
        print(f"* kb_id={kb['id']}  当前库名「{kb['name']}」  属主 {username}")
        print(f"    期望目录: {expected.relative_to(base)}/  （现有 {expected_n} 个文档）")
        for d, n in stray:
            print(f"    [x] 实际文档在: {d.relative_to(base)}/  （{n} 个文档）")
        print()

    print("=" * 72)
    print("说明：以上文档均未丢失，只是躺在旧库名目录里。")
    print("下一步将由迁移脚本把它们并入按 kb_id 命名的新目录（B1 方案）。")


if __name__ == "__main__":
    main()

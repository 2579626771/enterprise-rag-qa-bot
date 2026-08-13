"""多知识库隔离改造 —— 一次性迁移脚本（清空重建）。

背景：多知识库改造把 documents 表主键从单一 filename 改为复合主键 (kb_id, filename)，
文件目录从平铺 DOCUMENTS_DIR/ 改为按库分目录 DOCUMENTS_DIR/{kb_id}/，向量 metadata 增加 kb_id。
旧的存量数据（平铺文件、单集合向量、老 documents 表）与新结构不兼容。

用户已确认「清空重建」（数据可丢）。本脚本会：
  1. DROP TABLE documents（下次服务启动自动按新复合主键结构重建）
  2. 清空 data/chroma（向量库全清，删除旧集合）
  3. 清空 data/documents 下的平铺文件（保留按 kb 分的子目录不动，只删平铺的散文件）

用法：
    python -m scripts.migrate_multi_kb          # 交互确认后执行
    python -m scripts.migrate_multi_kb --yes    # 跳过确认（慎用）

注意：users / knowledge_bases / kb_quota_requests 表不受影响，由各服务
CREATE TABLE IF NOT EXISTS 自动维护；users.kb_quota 缺列会自动补。
"""

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import (  # noqa: E402
    CHROMA_DIR,
    DOCUMENTS_DIR,
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)


def _drop_documents_table() -> str:
    if not MYSQL_ENABLED:
        return "MYSQL_ENABLED=false，跳过删表。"
    import pymysql

    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS documents")
        conn.commit()
    finally:
        conn.close()
    return "已 DROP TABLE documents（服务下次启动会按新结构自动重建）。"


def _clear_chroma() -> str:
    d = Path(CHROMA_DIR)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return f"已清空向量库目录：{d}"
    return f"向量库目录不存在，跳过：{d}"


def _clear_flat_documents() -> str:
    d = Path(DOCUMENTS_DIR)
    if not d.exists():
        return f"文档目录不存在，跳过：{d}"
    removed = 0
    for entry in d.iterdir():
        # 只删平铺的散文件；按 kb 分的子目录（纯数字命名）保留不动。
        if entry.is_file():
            entry.unlink()
            removed += 1
    return f"已清除平铺散文件 {removed} 个（{d} 下的 kb 子目录保留）。"


def main() -> None:
    skip_confirm = "--yes" in sys.argv

    print("=" * 60)
    print("多知识库迁移（清空重建）将执行：")
    print(f"  1. DROP TABLE documents  @ {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
    print(f"  2. 清空向量库目录        {CHROMA_DIR}")
    print(f"  3. 清除平铺文档散文件    {DOCUMENTS_DIR}")
    print("=" * 60)
    print("此操作不可恢复。users / knowledge_bases / 配额申请表不受影响。")

    if not skip_confirm:
        ans = input("确认执行？输入 yes 继续：").strip().lower()
        if ans != "yes":
            print("已取消。")
            return

    print("- " + _drop_documents_table())
    print("- " + _clear_chroma())
    print("- " + _clear_flat_documents())
    print("完成。请重启后端；首个用户登录时会自动获得一个默认知识库。")


if __name__ == "__main__":
    main()

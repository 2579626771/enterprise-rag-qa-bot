"""文档元数据服务：把文档的分类/描述/上传时间/状态等持久化到 MySQL。

多知识库隔离后：每条记录归属一个 kb_id（知识库），主键为复合键 (kb_id, filename)。
同名文件可存在于不同知识库互不覆盖。

设计要点
--------
1. 两套仓库实现，接口一致：MySQLMetadataRepo（真实落库）/ InMemoryMetadataRepo（降级+测试）。
2. 懒连接 + 自动降级：连不上 MySQL 时切换到内存仓库，不拖垮主流程。
3. 自动建表：CREATE TABLE IF NOT EXISTS。

对外模块级函数：upsert / list_all / get / delete / delete_by_kb（均带 kb_id）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import (
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from app.utils.logger import get_logger

logger = get_logger("metadata_service")


def _default_meta(kb_id: int, filename: str) -> dict:
    return {
        "kb_id": kb_id,
        "filename": filename,
        "topic": "未分类",
        "description": "",
        "status": "就绪",
        "chunk_count": 0,
        "error": "",  # 后台入库失败时写入原因，供前端展示
        "uploaded_at": None,  # 由仓库在写入时补当前时间
    }


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _to_public(row: dict) -> dict:
    return {
        "kb_id": row.get("kb_id"),
        "filename": row["filename"],
        "topic": row.get("topic") or "未分类",
        "description": row.get("description") or "",
        "status": row.get("status") or "就绪",
        "chunk_count": int(row.get("chunk_count") or 0),
        "error": row.get("error") or "",
        "uploaded_at": _fmt_time(row.get("uploaded_at")),
    }


# ---------------------------------------------------------------------------
# 内存仓库：降级与测试用。key = (kb_id, filename)
# ---------------------------------------------------------------------------
class InMemoryMetadataRepo:
    def __init__(self) -> None:
        self._store: dict[tuple, dict] = {}

    def upsert(
        self,
        kb_id: int,
        filename: str,
        topic: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        chunk_count: Optional[int] = None,
        error: Optional[str] = None,
    ) -> dict:
        key = (kb_id, filename)
        row = self._store.get(key) or _default_meta(kb_id, filename)
        if topic is not None:
            row["topic"] = topic
        if description is not None:
            row["description"] = description
        if status is not None:
            row["status"] = status
        if chunk_count is not None:
            row["chunk_count"] = chunk_count
        if error is not None:
            row["error"] = error
        if row.get("uploaded_at") is None:
            row["uploaded_at"] = datetime.now()
        self._store[key] = row
        return _to_public(row)

    def list_all(self, kb_id: int) -> dict[str, dict]:
        return {
            fname: _to_public(row)
            for (kid, fname), row in self._store.items()
            if kid == kb_id
        }

    def get(self, kb_id: int, filename: str) -> Optional[dict]:
        row = self._store.get((kb_id, filename))
        return _to_public(row) if row else None

    def delete(self, kb_id: int, filename: str) -> bool:
        return self._store.pop((kb_id, filename), None) is not None

    def delete_by_kb(self, kb_id: int) -> int:
        keys = [k for k in self._store if k[0] == kb_id]
        for k in keys:
            del self._store[k]
        return len(keys)

    def rename_topic_in_kb(self, kb_id: int, old_name: str, new_name: str) -> int:
        """把某知识库下所有 topic==old_name 的文档改为 new_name。返回受影响条数。"""
        affected = 0
        for (kid, _fname), row in self._store.items():
            if kid == kb_id and row.get("topic") == old_name:
                row["topic"] = new_name
                affected += 1
        return affected


# ---------------------------------------------------------------------------
# MySQL 仓库：真实落库。复合主键 (kb_id, filename)
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    kb_id        INT          NOT NULL,
    filename     VARCHAR(512) NOT NULL,
    topic        VARCHAR(64)  NOT NULL DEFAULT '未分类',
    description  TEXT,
    status       VARCHAR(32)  NOT NULL DEFAULT '就绪',
    chunk_count  INT          NOT NULL DEFAULT 0,
    error        TEXT,
    uploaded_at  DATETIME     NOT NULL,
    updated_at   DATETIME     NOT NULL,
    PRIMARY KEY (kb_id, filename)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# 兼容旧库：老版本 documents 表没有 error 列，启动时补一列。
# 用 information_schema 判断存在与否，避免依赖 MySQL 版本的 IF NOT EXISTS 语法。
_ADD_ERROR_COLUMN_SQL = """
ALTER TABLE documents ADD COLUMN error TEXT NULL AFTER chunk_count
"""
_CHECK_ERROR_COLUMN_SQL = """
SELECT COUNT(*) AS c FROM information_schema.columns
WHERE table_schema = %s AND table_name = 'documents' AND column_name = 'error'
"""


class MySQLMetadataRepo:
    def __init__(self) -> None:
        import pymysql

        self._pymysql = pymysql
        self._ensure_table()

    def _connect(self):
        return self._pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=self._pymysql.cursors.DictCursor,
            autocommit=False,
        )

    def _ensure_table(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_TABLE_SQL)
                # 老库补列：error 不存在则新增，保证旧部署平滑升级。
                cur.execute(_CHECK_ERROR_COLUMN_SQL, (MYSQL_DATABASE,))
                row = cur.fetchone()
                has_error = bool(row and (row.get("c") if isinstance(row, dict) else row[0]))
                if not has_error:
                    cur.execute(_ADD_ERROR_COLUMN_SQL)
            conn.commit()
        finally:
            conn.close()

    def upsert(
        self,
        kb_id: int,
        filename: str,
        topic: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        chunk_count: Optional[int] = None,
        error: Optional[str] = None,
    ) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents
                        (kb_id, filename, topic, description, status, chunk_count, error, uploaded_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        topic       = COALESCE(%s, topic),
                        description = COALESCE(%s, description),
                        status      = COALESCE(%s, status),
                        chunk_count = COALESCE(%s, chunk_count),
                        error       = COALESCE(%s, error),
                        updated_at  = %s
                    """,
                    (
                        kb_id,
                        filename,
                        topic if topic is not None else "未分类",
                        description if description is not None else "",
                        status if status is not None else "就绪",
                        chunk_count if chunk_count is not None else 0,
                        error if error is not None else "",
                        now,
                        now,
                        # ON DUPLICATE 部分
                        topic,
                        description,
                        status,
                        chunk_count,
                        error,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get(kb_id, filename)

    def list_all(self, kb_id: int) -> dict[str, dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kb_id, filename, topic, description, status, chunk_count, error, uploaded_at "
                    "FROM documents WHERE kb_id = %s",
                    (kb_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return {row["filename"]: _to_public(row) for row in rows}

    def get(self, kb_id: int, filename: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kb_id, filename, topic, description, status, chunk_count, error, uploaded_at "
                    "FROM documents WHERE kb_id = %s AND filename = %s",
                    (kb_id, filename),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        return _to_public(row) if row else None

    def delete(self, kb_id: int, filename: str) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "DELETE FROM documents WHERE kb_id = %s AND filename = %s",
                    (kb_id, filename),
                )
            conn.commit()
        finally:
            conn.close()
        return affected > 0

    def delete_by_kb(self, kb_id: int) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute("DELETE FROM documents WHERE kb_id = %s", (kb_id,))
            conn.commit()
        finally:
            conn.close()
        return affected

    def rename_topic_in_kb(self, kb_id: int, old_name: str, new_name: str) -> int:
        """把某知识库下所有 topic==old_name 的文档改为 new_name。返回受影响条数。"""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE documents SET topic = %s WHERE kb_id = %s AND topic = %s",
                    (new_name, kb_id, old_name),
                )
            conn.commit()
        finally:
            conn.close()
        return affected


# ---------------------------------------------------------------------------
# 仓库单例管理：懒初始化 + 失败降级。
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        logger.info("MYSQL_ENABLED=false，文档元数据使用内存仓库（不落盘）。")
        return InMemoryMetadataRepo()
    try:
        repo = MySQLMetadataRepo()
        logger.info("文档元数据已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，降级为内存元数据（仅不落盘，问答/上传不受影响）：%s", exc)
        return InMemoryMetadataRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def upsert(
    kb_id: int,
    filename: str,
    topic: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    chunk_count: Optional[int] = None,
    error: Optional[str] = None,
) -> dict:
    """在指定知识库下新增或更新一条文档元数据。"""
    return _get_repo().upsert(
        kb_id=kb_id,
        filename=filename,
        topic=topic,
        description=description,
        status=status,
        chunk_count=chunk_count,
        error=error,
    )


def list_all(kb_id: int) -> dict[str, dict]:
    """返回指定知识库下 {filename: 元数据} 映射。"""
    return _get_repo().list_all(kb_id)


def get(kb_id: int, filename: str) -> Optional[dict]:
    return _get_repo().get(kb_id, filename)


def delete(kb_id: int, filename: str) -> bool:
    return _get_repo().delete(kb_id, filename)


def delete_by_kb(kb_id: int) -> int:
    """删除某知识库的所有文档元数据（删库时级联）。返回删除条数。"""
    return _get_repo().delete_by_kb(kb_id)


def rename_topic_in_kb(kb_id: int, old_name: str, new_name: str) -> int:
    """把某知识库下所有用旧分类名的文档 topic 改为新名（分类重命名联动）。返回受影响条数。"""
    if old_name == new_name:
        return 0
    return _get_repo().rename_topic_in_kb(kb_id, old_name, new_name)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

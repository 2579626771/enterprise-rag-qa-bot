"""文档主题分类服务：把「知识主题」候选集按知识库（kb_id）持久化到 MySQL。

每个知识库有自己独立的一组分类，互不影响（隔离）。新建知识库时自动种入 8 个
默认分类；知识库属主（或管理员）可对本库分类做增删改查，包括默认分类。

设计要点
--------
1. 两套仓库实现，接口一致：MySQLTopicRepo（真实落库）/ InMemoryTopicRepo（降级+测试）。
2. 懒连接 + 自动降级：连不上 MySQL 时切换到内存仓库，不拖垮主流程。
3. 自动建表：按 (kb_id, name) 唯一；旧版无 kb_id 列的表检测到后 DROP 重建
   （旧数据仅为全局默认种子，可安全丢弃）。
4. 幂等新增：同库重复新增同名分类返回既有项，不报错。

对外模块级函数：list_topics / add_topic / rename_topic / delete_topic / get / seed_defaults。
"""

from __future__ import annotations

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

logger = get_logger("topic_service")

# 每个新知识库初始种入的默认分类。
DEFAULT_TOPICS = [
    "技术文档",
    "产品手册",
    "规章制度",
    "培训资料",
    "会议纪要",
    "研究报告",
    "常见问答",
    "其他",
]


def _to_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "kb_id": row["kb_id"],
        "name": row["name"],
        "sort_order": int(row.get("sort_order") or 0),
    }


# ---------------------------------------------------------------------------
# 内存仓库：降级与测试用。分类归属 kb_id，(kb_id, name) 唯一。
# ---------------------------------------------------------------------------
class InMemoryTopicRepo:
    def __init__(self) -> None:
        self._store: dict[int, dict] = {}
        self._seq = 0

    def list_topics(self, kb_id: int) -> list[dict]:
        rows = [r for r in self._store.values() if r["kb_id"] == kb_id]
        rows.sort(key=lambda r: (r["sort_order"], r["id"]))
        return [_to_public(r) for r in rows]

    def add_topic(self, kb_id: int, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名称不能为空")
        # 幂等：同库已存在同名则直接返回。
        for r in self._store.values():
            if r["kb_id"] == kb_id and r["name"] == name:
                return _to_public(r)
        self._seq += 1
        # sort_order 取该库当前最大值 + 1
        max_order = max(
            (r["sort_order"] for r in self._store.values() if r["kb_id"] == kb_id),
            default=0,
        )
        row = {"id": self._seq, "kb_id": kb_id, "name": name, "sort_order": max_order + 1}
        self._store[row["id"]] = row
        return _to_public(row)

    def get(self, topic_id: int) -> Optional[dict]:
        row = self._store.get(topic_id)
        return _to_public(row) if row else None

    def rename_topic(self, topic_id: int, new_name: str) -> Optional[dict]:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("分类名称不能为空")
        row = self._store.get(topic_id)
        if row is None:
            return None
        old_name = row["name"]
        # 同库若已有同名（且不是自己），拒绝重命名以免撞唯一约束。
        for r in self._store.values():
            if r["kb_id"] == row["kb_id"] and r["name"] == new_name and r["id"] != topic_id:
                raise ValueError("该知识库下已存在同名分类")
        row["name"] = new_name
        return {"id": topic_id, "kb_id": row["kb_id"], "old_name": old_name, "new_name": new_name}

    def delete_topic(self, topic_id: int) -> bool:
        return self._store.pop(topic_id, None) is not None

    def seed_defaults(self, kb_id: int) -> None:
        for name in DEFAULT_TOPICS:
            self.add_topic(kb_id, name)


# ---------------------------------------------------------------------------
# MySQL 仓库：真实落库。(kb_id, name) 唯一。
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS topic_categories (
    id          INT          NOT NULL AUTO_INCREMENT,
    kb_id       INT          NOT NULL,
    name        VARCHAR(64)  NOT NULL,
    sort_order  INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uniq_kb_name (kb_id, name),
    KEY idx_kb (kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# 旧版本 topic_categories 表没有 kb_id 列（上一轮的全局字典）。用 information_schema
# 判断是否存在旧结构；存在则 DROP 后重建（旧数据仅为默认种子，可安全丢弃）。
_CHECK_KB_COLUMN_SQL = """
SELECT COUNT(*) AS c FROM information_schema.columns
WHERE table_schema = %s AND table_name = 'topic_categories' AND column_name = 'kb_id'
"""
_CHECK_TABLE_EXISTS_SQL = """
SELECT COUNT(*) AS c FROM information_schema.tables
WHERE table_schema = %s AND table_name = 'topic_categories'
"""


class MySQLTopicRepo:
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

    @staticmethod
    def _scalar(row) -> int:
        if not row:
            return 0
        return int(row.get("c") if isinstance(row, dict) else row[0])

    def _ensure_table(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 旧表迁移：若表已存在但没有 kb_id 列 → DROP 重建。
                cur.execute(_CHECK_TABLE_EXISTS_SQL, (MYSQL_DATABASE,))
                exists = self._scalar(cur.fetchone())
                if exists:
                    cur.execute(_CHECK_KB_COLUMN_SQL, (MYSQL_DATABASE,))
                    has_kb = self._scalar(cur.fetchone())
                    if not has_kb:
                        logger.info("检测到旧版全局 topic_categories 表，DROP 后按 kb_id 重建。")
                        cur.execute("DROP TABLE topic_categories")
                cur.execute(_CREATE_TABLE_SQL)
            conn.commit()
        finally:
            conn.close()

    def list_topics(self, kb_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, kb_id, name, sort_order FROM topic_categories "
                    "WHERE kb_id = %s ORDER BY sort_order ASC, id ASC",
                    (kb_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_to_public(r) for r in rows]

    def add_topic(self, kb_id: int, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名称不能为空")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 幂等：同库已存在则返回既有项。
                cur.execute(
                    "SELECT id, kb_id, name, sort_order FROM topic_categories "
                    "WHERE kb_id = %s AND name = %s",
                    (kb_id, name),
                )
                existing = cur.fetchone()
                if existing:
                    return _to_public(existing)
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) AS m FROM topic_categories WHERE kb_id = %s",
                    (kb_id,),
                )
                mrow = cur.fetchone()
                next_order = (mrow.get("m") if isinstance(mrow, dict) else mrow[0]) + 1
                cur.execute(
                    "INSERT INTO topic_categories (kb_id, name, sort_order) VALUES (%s, %s, %s)",
                    (kb_id, name, next_order),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return {"id": new_id, "kb_id": kb_id, "name": name, "sort_order": next_order}

    def get(self, topic_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, kb_id, name, sort_order FROM topic_categories WHERE id = %s",
                    (topic_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        return _to_public(row) if row else None

    def rename_topic(self, topic_id: int, new_name: str) -> Optional[dict]:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("分类名称不能为空")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, kb_id, name FROM topic_categories WHERE id = %s", (topic_id,)
                )
                row = cur.fetchone()
                if row is None:
                    return None
                kb_id = row["kb_id"]
                old_name = row["name"]
                if new_name == old_name:
                    return {"id": topic_id, "kb_id": kb_id, "old_name": old_name, "new_name": new_name}
                # 同库若已有同名（不是自己）→ 拒绝。
                cur.execute(
                    "SELECT id FROM topic_categories WHERE kb_id = %s AND name = %s AND id <> %s",
                    (kb_id, new_name, topic_id),
                )
                if cur.fetchone():
                    raise ValueError("该知识库下已存在同名分类")
                cur.execute(
                    "UPDATE topic_categories SET name = %s WHERE id = %s", (new_name, topic_id)
                )
            conn.commit()
        finally:
            conn.close()
        return {"id": topic_id, "kb_id": kb_id, "old_name": old_name, "new_name": new_name}

    def delete_topic(self, topic_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute("DELETE FROM topic_categories WHERE id = %s", (topic_id,))
            conn.commit()
        finally:
            conn.close()
        return affected > 0

    def seed_defaults(self, kb_id: int) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for i, name in enumerate(DEFAULT_TOPICS, start=1):
                    # 幂等：已存在则跳过（唯一约束保护）。
                    cur.execute(
                        "INSERT IGNORE INTO topic_categories (kb_id, name, sort_order) "
                        "VALUES (%s, %s, %s)",
                        (kb_id, name, i),
                    )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 仓库单例管理：懒初始化 + 失败降级。
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        logger.info("MYSQL_ENABLED=false，主题分类使用内存仓库（按库隔离，不落盘）。")
        return InMemoryTopicRepo()
    try:
        repo = MySQLTopicRepo()
        logger.info("主题分类已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，降级为内存主题分类（按库隔离，不落盘）：%s", exc)
        return InMemoryTopicRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def list_topics(kb_id: int) -> list[dict]:
    """返回某知识库的全部主题分类（按 sort_order 升序）。"""
    return _get_repo().list_topics(kb_id)


def add_topic(kb_id: int, name: str) -> dict:
    """在某知识库下新增一个分类（(kb_id,name) 唯一，幂等）。"""
    return _get_repo().add_topic(kb_id, name)


def get(topic_id: int) -> Optional[dict]:
    """按 id 取分类（含 kb_id，供上层做归属校验）。不存在返回 None。"""
    return _get_repo().get(topic_id)


def rename_topic(topic_id: int, new_name: str) -> Optional[dict]:
    """重命名分类。返回 {id, kb_id, old_name, new_name}；分类不存在返回 None。"""
    return _get_repo().rename_topic(topic_id, new_name)


def delete_topic(topic_id: int) -> bool:
    """删除分类。返回是否删除成功。"""
    return _get_repo().delete_topic(topic_id)


def seed_defaults(kb_id: int) -> None:
    """为某知识库种入默认分类（幂等）。建库时调用。"""
    _get_repo().seed_defaults(kb_id)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

"""知识库服务：知识库（knowledge_bases）的持久化与配额校验。

每个知识库属于一个 owner（users.id）。文档、向量、文件目录都按知识库 id 隔离。
沿用 metadata_service / user_service 的双仓库 + 懒连接 + 降级 + _set_repo_for_test 模式。

对外模块级 API：
    create_kb(owner_id, name, description, enforce_quota=True) -> kb
    get(kb_id) / list_by_owner(owner_id) / list_all() / delete(kb_id)
    count_by_owner(owner_id)
    ensure_default_kb(owner_id, ...) -> kb   # 用户首次登录/建号时保证有一个默认库
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
from app.services import user_service
from app.utils.logger import get_logger

logger = get_logger("kb_service")


class QuotaExceededError(Exception):
    """知识库数量超过配额上限。上层据此返回 403 并提示申请。"""


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "created_at": _fmt_time(row.get("created_at")),
    }


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryKbRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, dict] = {}
        self._seq = 0

    def create(self, owner_id: int, name: str, description: str) -> dict:
        self._seq += 1
        now = datetime.now()
        row = {
            "id": self._seq,
            "owner_id": owner_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
        }
        self._by_id[self._seq] = row
        return dict(row)

    def get(self, kb_id: int) -> Optional[dict]:
        row = self._by_id.get(kb_id)
        return dict(row) if row else None

    def update(self, kb_id: int, name: str, description: str) -> Optional[dict]:
        row = self._by_id.get(kb_id)
        if not row:
            return None
        row["name"] = name
        row["description"] = description
        row["updated_at"] = datetime.now()
        return dict(row)

    def list_by_owner(self, owner_id: int) -> list[dict]:
        return [
            dict(r)
            for r in sorted(self._by_id.values(), key=lambda r: r["id"])
            if r["owner_id"] == owner_id
        ]

    def list_all(self) -> list[dict]:
        return [dict(r) for r in sorted(self._by_id.values(), key=lambda r: r["id"])]

    def delete(self, kb_id: int) -> bool:
        return self._by_id.pop(kb_id, None) is not None

    def count_by_owner(self, owner_id: int) -> int:
        return sum(1 for r in self._by_id.values() if r["owner_id"] == owner_id)


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          INT          NOT NULL AUTO_INCREMENT,
    owner_id    INT          NOT NULL,
    name        VARCHAR(64)  NOT NULL,
    description VARCHAR(255),
    created_at  DATETIME     NOT NULL,
    updated_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLKbRepo:
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
            conn.commit()
        finally:
            conn.close()

    def create(self, owner_id: int, name: str, description: str) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_bases
                        (owner_id, name, description, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (owner_id, name, description, now, now),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get(new_id)

    def get(self, kb_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM knowledge_bases WHERE id = %s", (kb_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def update(self, kb_id: int, name: str, description: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_bases
                       SET name = %s, description = %s, updated_at = %s
                     WHERE id = %s
                    """,
                    (name, description, datetime.now(), kb_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get(kb_id)

    def list_by_owner(self, owner_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM knowledge_bases WHERE owner_id = %s ORDER BY id",
                    (owner_id,),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def list_all(self) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM knowledge_bases ORDER BY id")
                return list(cur.fetchall())
        finally:
            conn.close()

    def delete(self, kb_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "DELETE FROM knowledge_bases WHERE id = %s", (kb_id,)
                )
            conn.commit()
        finally:
            conn.close()
        return affected > 0

    def count_by_owner(self, owner_id: int) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM knowledge_bases WHERE owner_id = %s",
                    (owner_id,),
                )
                return int(cur.fetchone()["c"])
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 仓库单例管理
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        logger.info("MYSQL_ENABLED=false，知识库使用内存仓库（重启即失）。")
        return InMemoryKbRepo()
    try:
        repo = MySQLKbRepo()
        logger.info("知识库已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，知识库降级为内存仓库（重启即失）：%s", exc)
        return InMemoryKbRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def create_kb(
    owner_id: int,
    name: str,
    description: str = "",
    enforce_quota: bool = True,
) -> dict:
    """建库。enforce_quota=True 时校验该 owner 的库数是否已达配额上限。
    管理员不受配额限制（基于角色判断，不依赖 kb_quota 数值）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("知识库名称不能为空")
    owner = user_service.get_by_id(owner_id)
    is_admin = bool(owner and owner.get("role") == user_service.ROLE_ADMIN)
    if enforce_quota and not is_admin:
        used = _get_repo().count_by_owner(owner_id)
        quota = user_service.get_quota(owner_id)
        if used >= quota:
            raise QuotaExceededError(
                f"已达知识库上限（{used}/{quota}），请向管理员申请更多配额"
            )
    row = _get_repo().create(owner_id=owner_id, name=name, description=(description or "").strip())
    return _public(row)


def get(kb_id: int) -> Optional[dict]:
    row = _get_repo().get(kb_id)
    return _public(row) if row else None


def update_kb(kb_id: int, name: str, description: str = "") -> Optional[dict]:
    """更新知识库名称与描述。name 不能为空；返回更新后的公开视图，库不存在返回 None。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("知识库名称不能为空")
    row = _get_repo().update(kb_id, name, (description or "").strip())
    return _public(row) if row else None


def list_by_owner(owner_id: int) -> list[dict]:
    return [_public(r) for r in _get_repo().list_by_owner(owner_id)]


def list_all() -> list[dict]:
    return [_public(r) for r in _get_repo().list_all()]


def delete(kb_id: int) -> bool:
    return _get_repo().delete(kb_id)


def count_by_owner(owner_id: int) -> int:
    return _get_repo().count_by_owner(owner_id)


def is_owner(kb_id: int, user_id: int) -> bool:
    """判断某知识库是否属于某用户。"""
    row = _get_repo().get(kb_id)
    return bool(row and row["owner_id"] == user_id)


def ensure_default_kb(owner_id: int, name: str = "我的知识库", description: str = "默认知识库") -> dict:
    """保证用户至少有一个知识库；已有则返回其第一个库，没有则建一个（不占配额校验）。"""
    existing = _get_repo().list_by_owner(owner_id)
    if existing:
        return _public(existing[0])
    return create_kb(owner_id, name, description, enforce_quota=False)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

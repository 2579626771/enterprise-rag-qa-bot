"""配额申请服务：普通用户申请额外知识库配额，管理员审批。

工作流：
    用户 create_request(amount, reason) → status=pending
    管理员 approve(request_id, admin_id) → status=approved，并给申请人加配额
    管理员 reject(request_id, admin_id)  → status=rejected

沿用双仓库 + 懒连接 + 降级 + _set_repo_for_test 模式。
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
    require_mysql,
)
from app.services import user_service
from app.utils.logger import get_logger

logger = get_logger("quota_service")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "amount": int(row.get("amount") or 0),
        "reason": row.get("reason") or "",
        "status": row.get("status") or STATUS_PENDING,
        "reviewed_by": row.get("reviewed_by"),
        "created_at": _fmt_time(row.get("created_at")),
        "reviewed_at": _fmt_time(row.get("reviewed_at")),
    }


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryQuotaRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, dict] = {}
        self._seq = 0

    def create(self, user_id: int, amount: int, reason: str) -> dict:
        self._seq += 1
        row = {
            "id": self._seq,
            "user_id": user_id,
            "amount": amount,
            "reason": reason,
            "status": STATUS_PENDING,
            "reviewed_by": None,
            "created_at": datetime.now(),
            "reviewed_at": None,
        }
        self._by_id[self._seq] = row
        return dict(row)

    def get(self, request_id: int) -> Optional[dict]:
        row = self._by_id.get(request_id)
        return dict(row) if row else None

    def list_pending(self) -> list[dict]:
        return [
            dict(r)
            for r in sorted(self._by_id.values(), key=lambda r: r["id"])
            if r["status"] == STATUS_PENDING
        ]

    def list_by_user(self, user_id: int) -> list[dict]:
        return [
            dict(r)
            for r in sorted(self._by_id.values(), key=lambda r: r["id"], reverse=True)
            if r["user_id"] == user_id
        ]

    def set_status(self, request_id: int, status: str, admin_id: int) -> bool:
        row = self._by_id.get(request_id)
        if not row:
            return False
        row["status"] = status
        row["reviewed_by"] = admin_id
        row["reviewed_at"] = datetime.now()
        return True


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kb_quota_requests (
    id          INT          NOT NULL AUTO_INCREMENT,
    user_id     INT          NOT NULL,
    amount      INT          NOT NULL,
    reason      VARCHAR(255),
    status      VARCHAR(16)  NOT NULL DEFAULT 'pending',
    reviewed_by INT,
    created_at  DATETIME     NOT NULL,
    reviewed_at DATETIME,
    PRIMARY KEY (id),
    KEY idx_user (user_id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLQuotaRepo:
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

    def create(self, user_id: int, amount: int, reason: str) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_quota_requests
                        (user_id, amount, reason, status, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, amount, reason, STATUS_PENDING, now),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get(new_id)

    def get(self, request_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM kb_quota_requests WHERE id = %s", (request_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def list_pending(self) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM kb_quota_requests WHERE status = %s ORDER BY id",
                    (STATUS_PENDING,),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def list_by_user(self, user_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM kb_quota_requests WHERE user_id = %s ORDER BY id DESC",
                    (user_id,),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def set_status(self, request_id: int, status: str, admin_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE kb_quota_requests SET status = %s, reviewed_by = %s, reviewed_at = %s "
                    "WHERE id = %s AND status = %s",
                    (status, admin_id, datetime.now(), request_id, STATUS_PENDING),
                )
            conn.commit()
        finally:
            conn.close()
        return affected > 0


# ---------------------------------------------------------------------------
# 仓库单例管理
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        if require_mysql():
            raise RuntimeError("生产环境必须启用 MySQL，不能使用内存配额仓库")
        logger.info("MYSQL_ENABLED=false，配额申请使用内存仓库（重启即失）。")
        return InMemoryQuotaRepo()
    try:
        repo = MySQLQuotaRepo()
        logger.info("配额申请已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        if require_mysql():
            raise RuntimeError(f"生产环境连接 MySQL 失败，配额仓库不可降级：{exc}") from exc
        logger.warning("接入 MySQL 失败，配额申请降级为内存仓库（重启即失）：%s", exc)
        return InMemoryQuotaRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def create_request(user_id: int, amount: int, reason: str = "") -> dict:
    """提交一条配额申请。amount 必须为正整数。"""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("申请数量必须大于 0")
    row = _get_repo().create(user_id=user_id, amount=amount, reason=(reason or "").strip())
    return _public(row)


def list_pending() -> list[dict]:
    return [_public(r) for r in _get_repo().list_pending()]


def list_by_user(user_id: int) -> list[dict]:
    return [_public(r) for r in _get_repo().list_by_user(user_id)]


def get(request_id: int) -> Optional[dict]:
    row = _get_repo().get(request_id)
    return _public(row) if row else None


def approve(request_id: int, admin_id: int) -> dict:
    """通过申请：把状态置 approved，并给申请人增加配额。"""
    row = _get_repo().get(request_id)
    if not row:
        raise ValueError("申请不存在")
    if row["status"] != STATUS_PENDING:
        raise ValueError("该申请已被处理")
    if not _get_repo().set_status(request_id, STATUS_APPROVED, admin_id):
        raise ValueError("该申请已被处理")
    user_service.increase_quota(row["user_id"], row["amount"])
    return _public(_get_repo().get(request_id))


def reject(request_id: int, admin_id: int) -> dict:
    """驳回申请：仅置状态，不改配额。"""
    row = _get_repo().get(request_id)
    if not row:
        raise ValueError("申请不存在")
    if row["status"] != STATUS_PENDING:
        raise ValueError("该申请已被处理")
    if not _get_repo().set_status(request_id, STATUS_REJECTED, admin_id):
        raise ValueError("该申请已被处理")
    return _public(_get_repo().get(request_id))


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

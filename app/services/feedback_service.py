"""问题反馈服务：用户提交反馈，管理员处理并回复。

工作流：
    用户 create_ticket(title, content) → status=pending
    管理员 admin_update(status=processing/resolved, reply=...) → 写入处理状态/回复
    用户 close_ticket() → status=closed

沿用项目内服务层的双仓库 + 懒连接 + MySQL 自动建表 + 内存降级模式。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import (
    FEEDBACK_ATTACHMENT_MAX_COUNT,
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    require_mysql,
)
from app.utils.logger import get_logger

logger = get_logger("feedback_service")

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"
VALID_STATUSES = {STATUS_PENDING, STATUS_PROCESSING, STATUS_RESOLVED, STATUS_CLOSED}
ADMIN_TARGET_STATUSES = {STATUS_PROCESSING, STATUS_RESOLVED, STATUS_CLOSED}

TITLE_MAX_LEN = 120
CONTENT_MAX_LEN = 4000
REPLY_MAX_LEN = 4000


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _validate_title(title: str) -> str:
    value = (title or "").strip()
    if not value:
        raise ValueError("反馈标题不能为空")
    if len(value) > TITLE_MAX_LEN:
        raise ValueError(f"反馈标题不能超过 {TITLE_MAX_LEN} 个字符")
    return value


def _validate_text(value: str, max_len: int, field_name: str) -> str:
    text = (value or "").strip()
    if len(text) > max_len:
        raise ValueError(f"{field_name}不能超过 {max_len} 个字符")
    return text


def _attachment_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "ticket_id": row["ticket_id"],
        "filename": row.get("original_name") or "截图",
        "content_type": row.get("content_type") or "application/octet-stream",
        "size": int(row.get("size") or 0),
        "created_at": _fmt_time(row.get("created_at")),
    }


def _public(row: dict, attachments: Optional[list[dict]] = None) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "status": row.get("status") or STATUS_PENDING,
        "admin_reply": row.get("admin_reply") or "",
        "resolved_by": row.get("resolved_by"),
        "created_at": _fmt_time(row.get("created_at")),
        "updated_at": _fmt_time(row.get("updated_at")),
        "resolved_at": _fmt_time(row.get("resolved_at")),
        "attachments": [_attachment_public(a) for a in (attachments or [])],
    }


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryFeedbackRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, dict] = {}
        self._attachments: dict[int, dict] = {}
        self._seq = 0
        self._attachment_seq = 0

    def create(self, user_id: int, title: str, content: str) -> dict:
        self._seq += 1
        now = datetime.now()
        row = {
            "id": self._seq,
            "user_id": user_id,
            "title": title,
            "content": content,
            "status": STATUS_PENDING,
            "admin_reply": "",
            "resolved_by": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }
        self._by_id[row["id"]] = row
        return dict(row)

    def get(self, ticket_id: int) -> Optional[dict]:
        row = self._by_id.get(ticket_id)
        return dict(row) if row else None

    def list_by_user(self, user_id: int) -> list[dict]:
        rows = [r for r in self._by_id.values() if r["user_id"] == user_id]
        rows.sort(key=lambda r: (r.get("updated_at") or r.get("created_at"), r["id"]), reverse=True)
        return [dict(r) for r in rows]

    def list_all(self, status: Optional[str] = None) -> list[dict]:
        rows = list(self._by_id.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        rows.sort(key=lambda r: (r.get("updated_at") or r.get("created_at"), r["id"]), reverse=True)
        return [dict(r) for r in rows]

    def admin_update(self, ticket_id: int, status: str, reply: str, admin_id: int) -> Optional[dict]:
        row = self._by_id.get(ticket_id)
        if not row:
            return None
        now = datetime.now()
        row["status"] = status
        row["admin_reply"] = reply
        row["resolved_by"] = admin_id if status in (STATUS_RESOLVED, STATUS_CLOSED) else row.get("resolved_by")
        row["resolved_at"] = now if status in (STATUS_RESOLVED, STATUS_CLOSED) else row.get("resolved_at")
        row["updated_at"] = now
        return dict(row)

    def close(self, ticket_id: int, user_id: int) -> Optional[dict]:
        row = self._by_id.get(ticket_id)
        if row is None or row["user_id"] != user_id:
            return None
        now = datetime.now()
        row["status"] = STATUS_CLOSED
        row["updated_at"] = now
        if row.get("resolved_at") is None:
            row["resolved_at"] = now
        return dict(row)

    def add_attachment(
        self,
        ticket_id: int,
        original_name: str,
        stored_name: str,
        content_type: str,
        size: int,
    ) -> dict:
        self._attachment_seq += 1
        row = {
            "id": self._attachment_seq,
            "ticket_id": ticket_id,
            "original_name": original_name,
            "stored_name": stored_name,
            "content_type": content_type,
            "size": size,
            "created_at": datetime.now(),
        }
        self._attachments[row["id"]] = row
        return dict(row)

    def list_attachments(self, ticket_id: int) -> list[dict]:
        rows = [r for r in self._attachments.values() if r["ticket_id"] == ticket_id]
        rows.sort(key=lambda r: r["id"])
        return [dict(r) for r in rows]

    def get_attachment(self, attachment_id: int) -> Optional[dict]:
        row = self._attachments.get(attachment_id)
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS feedback_tickets (
    id           INT          NOT NULL AUTO_INCREMENT,
    user_id      INT          NOT NULL,
    title        VARCHAR(120) NOT NULL,
    content      TEXT,
    status       VARCHAR(16)  NOT NULL DEFAULT 'pending',
    admin_reply  TEXT,
    resolved_by  INT,
    created_at   DATETIME     NOT NULL,
    updated_at   DATETIME     NOT NULL,
    resolved_at  DATETIME,
    PRIMARY KEY (id),
    KEY idx_user (user_id),
    KEY idx_status (status),
    KEY idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_ATTACHMENTS_SQL = """
CREATE TABLE IF NOT EXISTS feedback_attachments (
    id            INT          NOT NULL AUTO_INCREMENT,
    ticket_id     INT          NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_name   VARCHAR(255) NOT NULL,
    content_type  VARCHAR(64)  NOT NULL,
    size          INT          NOT NULL,
    created_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_ticket (ticket_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLFeedbackRepo:
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
                cur.execute(_CREATE_ATTACHMENTS_SQL)
            conn.commit()
        finally:
            conn.close()

    def create(self, user_id: int, title: str, content: str) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feedback_tickets
                        (user_id, title, content, status, admin_reply, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, title, content, STATUS_PENDING, "", now, now),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get(new_id)

    def get(self, ticket_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM feedback_tickets WHERE id = %s", (ticket_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def list_by_user(self, user_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM feedback_tickets WHERE user_id = %s ORDER BY updated_at DESC, id DESC",
                    (user_id,),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def list_all(self, status: Optional[str] = None) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM feedback_tickets WHERE status = %s ORDER BY updated_at DESC, id DESC",
                        (status,),
                    )
                else:
                    cur.execute("SELECT * FROM feedback_tickets ORDER BY updated_at DESC, id DESC")
                return list(cur.fetchall())
        finally:
            conn.close()

    def admin_update(self, ticket_id: int, status: str, reply: str, admin_id: int) -> Optional[dict]:
        now = datetime.now()
        resolved_at = now if status in (STATUS_RESOLVED, STATUS_CLOSED) else None
        resolved_by = admin_id if status in (STATUS_RESOLVED, STATUS_CLOSED) else None
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE feedback_tickets
                    SET status = %s, admin_reply = %s, resolved_by = %s,
                        resolved_at = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (status, reply, resolved_by, resolved_at, now, ticket_id),
                )
            conn.commit()
        finally:
            conn.close()
        if affected <= 0:
            return None
        return self.get(ticket_id)

    def close(self, ticket_id: int, user_id: int) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE feedback_tickets
                    SET status = %s, updated_at = %s,
                        resolved_at = COALESCE(resolved_at, %s)
                    WHERE id = %s AND user_id = %s
                    """,
                    (STATUS_CLOSED, now, now, ticket_id, user_id),
                )
            conn.commit()
        finally:
            conn.close()
        if affected <= 0:
            return None
        return self.get(ticket_id)

    def add_attachment(
        self,
        ticket_id: int,
        original_name: str,
        stored_name: str,
        content_type: str,
        size: int,
    ) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feedback_attachments
                        (ticket_id, original_name, stored_name, content_type, size, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (ticket_id, original_name, stored_name, content_type, size, now),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_attachment(new_id)

    def list_attachments(self, ticket_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM feedback_attachments WHERE ticket_id = %s ORDER BY id",
                    (ticket_id,),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def get_attachment(self, attachment_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM feedback_attachments WHERE id = %s", (attachment_id,))
                return cur.fetchone()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 仓库单例管理
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        if require_mysql():
            raise RuntimeError("生产环境必须启用 MySQL，不能使用内存反馈仓库")
        logger.info("MYSQL_ENABLED=false，问题反馈使用内存仓库（重启即失）。")
        return InMemoryFeedbackRepo()
    try:
        repo = MySQLFeedbackRepo()
        logger.info("问题反馈已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        if require_mysql():
            raise RuntimeError(f"生产环境连接 MySQL 失败，反馈仓库不可降级：{exc}") from exc
        logger.warning("接入 MySQL 失败，问题反馈降级为内存仓库（重启即失）：%s", exc)
        return InMemoryFeedbackRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def create_ticket(user_id: int, title: str, content: str = "") -> dict:
    title = _validate_title(title)
    content = _validate_text(content, CONTENT_MAX_LEN, "反馈内容")
    row = _get_repo().create(user_id=user_id, title=title, content=content)
    return _public(row, _get_repo().list_attachments(row["id"]))


def _public_with_attachments(row: dict) -> dict:
    return _public(row, _get_repo().list_attachments(row["id"]))


def list_by_user(user_id: int) -> list[dict]:
    return [_public_with_attachments(r) for r in _get_repo().list_by_user(user_id)]


def list_all(status: Optional[str] = None) -> list[dict]:
    value = (status or "").strip()
    if value in ("", "all"):
        value = None
    elif value not in VALID_STATUSES:
        raise ValueError("反馈状态不合法")
    return [_public_with_attachments(r) for r in _get_repo().list_all(value)]


def get(ticket_id: int) -> Optional[dict]:
    row = _get_repo().get(ticket_id)
    return _public_with_attachments(row) if row else None


def admin_update(ticket_id: int, status: str, reply: str, admin_id: int) -> dict:
    value = (status or "").strip()
    if value not in ADMIN_TARGET_STATUSES:
        raise ValueError("反馈状态不合法")
    reply = _validate_text(reply, REPLY_MAX_LEN, "处理回复")
    if value == STATUS_RESOLVED and not reply:
        raise ValueError("标记已解决时必须填写处理回复")
    row = _get_repo().admin_update(ticket_id, value, reply, admin_id)
    if row is None:
        raise ValueError("反馈不存在")
    return _public_with_attachments(row)


def close_ticket(ticket_id: int, user_id: int) -> Optional[dict]:
    row = _get_repo().close(ticket_id, user_id)
    return _public_with_attachments(row) if row else None


def add_attachment(
    ticket_id: int,
    original_name: str,
    stored_name: str,
    content_type: str,
    size: int,
) -> dict:
    if get(ticket_id) is None:
        raise ValueError("反馈不存在")
    if len(_get_repo().list_attachments(ticket_id)) >= FEEDBACK_ATTACHMENT_MAX_COUNT:
        raise ValueError(f"每条反馈最多上传 {FEEDBACK_ATTACHMENT_MAX_COUNT} 张截图")
    row = _get_repo().add_attachment(ticket_id, original_name, stored_name, content_type, size)
    return _attachment_public(row)


def list_attachments(ticket_id: int) -> list[dict]:
    return [_attachment_public(r) for r in _get_repo().list_attachments(ticket_id)]


def get_attachment(attachment_id: int) -> Optional[dict]:
    row = _get_repo().get_attachment(attachment_id)
    return _attachment_public(row) if row else None


def get_attachment_record(attachment_id: int) -> Optional[dict]:
    """取附件原始记录（含 stored_name），仅供后端鉴权下载接口内部使用。"""
    return _get_repo().get_attachment(attachment_id)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

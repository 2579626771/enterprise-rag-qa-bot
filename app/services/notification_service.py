"""通知服务：管理员下发通知，用户在消息中心查看、已读或关闭。

设计要点：
1. 通知主体 notifications 与收件人状态 notification_recipients 分离。
2. 创建时物化每个接收人的 recipient 行，未读/已读/关闭状态按用户独立保存。
3. 沿用双仓库 + 懒连接 + MySQL 自动建表 + 内存降级模式。
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
from app.utils.logger import get_logger

logger = get_logger("notification_service")

TARGET_ALL = "all"
TARGET_USERS = "users"
VALID_TARGETS = {TARGET_ALL, TARGET_USERS}

STATUS_UNREAD = "unread"
STATUS_READ = "read"
STATUS_CLOSED = "closed"
VALID_STATUSES = {STATUS_UNREAD, STATUS_READ, STATUS_CLOSED}

TITLE_MAX_LEN = 120
CONTENT_MAX_LEN = 4000


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _validate_title(title: str) -> str:
    value = (title or "").strip()
    if not value:
        raise ValueError("通知标题不能为空")
    if len(value) > TITLE_MAX_LEN:
        raise ValueError(f"通知标题不能超过 {TITLE_MAX_LEN} 个字符")
    return value


def _validate_content(content: str) -> str:
    value = (content or "").strip()
    if len(value) > CONTENT_MAX_LEN:
        raise ValueError(f"通知内容不能超过 {CONTENT_MAX_LEN} 个字符")
    return value


def _dedupe_user_ids(user_ids: list[int]) -> list[int]:
    seen = set()
    out = []
    for user_id in user_ids or []:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _user_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "created_by": row.get("created_by"),
        "target_type": row.get("target_type") or TARGET_USERS,
        "status": row.get("status") or STATUS_UNREAD,
        "created_at": _fmt_time(row.get("created_at")),
        "read_at": _fmt_time(row.get("read_at")),
        "closed_at": _fmt_time(row.get("closed_at")),
    }


def _admin_public(row: dict) -> dict:
    recipient_count = int(row.get("recipient_count") or 0)
    unread_count = int(row.get("unread_count") or 0)
    read_count = int(row.get("read_count") or 0)
    closed_count = int(row.get("closed_count") or 0)
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "created_by": row.get("created_by"),
        "target_type": row.get("target_type") or TARGET_USERS,
        "created_at": _fmt_time(row.get("created_at")),
        "recipient_count": recipient_count,
        "unread_count": unread_count,
        "read_count": read_count,
        "closed_count": closed_count,
    }


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryNotificationRepo:
    def __init__(self) -> None:
        self._notifications: dict[int, dict] = {}
        self._recipients: dict[int, dict] = {}
        self._notification_seq = 0
        self._recipient_seq = 0

    def create(self, title: str, content: str, created_by: int, target_type: str, user_ids: list[int]) -> dict:
        self._notification_seq += 1
        now = datetime.now()
        row = {
            "id": self._notification_seq,
            "title": title,
            "content": content,
            "created_by": created_by,
            "target_type": target_type,
            "created_at": now,
        }
        self._notifications[row["id"]] = row
        for user_id in user_ids:
            self._recipient_seq += 1
            self._recipients[self._recipient_seq] = {
                "id": self._recipient_seq,
                "notification_id": row["id"],
                "user_id": user_id,
                "status": STATUS_UNREAD,
                "read_at": None,
                "closed_at": None,
            }
        recipients = [r for r in self._recipients.values() if r["notification_id"] == row["id"]]
        return {
            **row,
            "recipient_count": len(recipients),
            "unread_count": len(recipients),
            "read_count": 0,
            "closed_count": 0,
        }

    def _joined(self, recipient: dict) -> Optional[dict]:
        notification = self._notifications.get(recipient["notification_id"])
        if not notification:
            return None
        return {**notification, **recipient, "id": notification["id"], "recipient_id": recipient["id"]}

    def list_for_user(self, user_id: int, include_closed: bool = False) -> list[dict]:
        rows = []
        for recipient in self._recipients.values():
            if recipient["user_id"] != user_id:
                continue
            if not include_closed and recipient.get("status") == STATUS_CLOSED:
                continue
            joined = self._joined(recipient)
            if joined:
                rows.append(joined)
        rows.sort(key=lambda r: (r.get("created_at"), r["id"]), reverse=True)
        return [dict(r) for r in rows]

    def count_unread(self, user_id: int) -> int:
        return sum(
            1
            for r in self._recipients.values()
            if r["user_id"] == user_id and r.get("status") == STATUS_UNREAD
        )

    def set_status(self, notification_id: int, user_id: int, status: str) -> Optional[dict]:
        for recipient in self._recipients.values():
            if recipient["notification_id"] == notification_id and recipient["user_id"] == user_id:
                now = datetime.now()
                recipient["status"] = status
                if status == STATUS_READ:
                    recipient["read_at"] = recipient.get("read_at") or now
                if status == STATUS_CLOSED:
                    recipient["closed_at"] = recipient.get("closed_at") or now
                    recipient["read_at"] = recipient.get("read_at") or now
                return self._joined(recipient)
        return None

    def list_admin(self, created_by: Optional[int] = None) -> list[dict]:
        rows = []
        for n in self._notifications.values():
            if created_by is not None and n.get("created_by") != created_by:
                continue
            recipients = [r for r in self._recipients.values() if r["notification_id"] == n["id"]]
            rows.append(
                {
                    **n,
                    "recipient_count": len(recipients),
                    "unread_count": sum(1 for r in recipients if r["status"] == STATUS_UNREAD),
                    "read_count": sum(1 for r in recipients if r["status"] == STATUS_READ),
                    "closed_count": sum(1 for r in recipients if r["status"] == STATUS_CLOSED),
                }
            )
        rows.sort(key=lambda r: (r.get("created_at"), r["id"]), reverse=True)
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_NOTIFICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INT          NOT NULL AUTO_INCREMENT,
    title       VARCHAR(120) NOT NULL,
    content     TEXT,
    created_by  INT          NOT NULL,
    target_type VARCHAR(16)  NOT NULL,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_creator (created_by),
    KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_RECIPIENTS_SQL = """
CREATE TABLE IF NOT EXISTS notification_recipients (
    id              INT         NOT NULL AUTO_INCREMENT,
    notification_id INT         NOT NULL,
    user_id         INT         NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'unread',
    read_at         DATETIME,
    closed_at       DATETIME,
    PRIMARY KEY (id),
    KEY idx_user_status (user_id, status),
    KEY idx_notification (notification_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLNotificationRepo:
    def __init__(self) -> None:
        import pymysql

        self._pymysql = pymysql
        self._ensure_tables()

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

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_NOTIFICATIONS_SQL)
                cur.execute(_CREATE_RECIPIENTS_SQL)
            conn.commit()
        finally:
            conn.close()

    def create(self, title: str, content: str, created_by: int, target_type: str, user_ids: list[int]) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications (title, content, created_by, target_type, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (title, content, created_by, target_type, now),
                )
                notification_id = cur.lastrowid
                for user_id in user_ids:
                    cur.execute(
                        """
                        INSERT INTO notification_recipients
                            (notification_id, user_id, status)
                        VALUES (%s, %s, %s)
                        """,
                        (notification_id, user_id, STATUS_UNREAD),
                    )
            conn.commit()
        finally:
            conn.close()
        rows = self.list_admin()
        return next(r for r in rows if r["id"] == notification_id)

    def list_for_user(self, user_id: int, include_closed: bool = False) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                where = "r.user_id = %s"
                params = [user_id]
                if not include_closed:
                    where += " AND r.status <> %s"
                    params.append(STATUS_CLOSED)
                cur.execute(
                    f"""
                    SELECT n.id, n.title, n.content, n.created_by, n.target_type, n.created_at,
                           r.status, r.read_at, r.closed_at
                    FROM notification_recipients r
                    JOIN notifications n ON n.id = r.notification_id
                    WHERE {where}
                    ORDER BY n.created_at DESC, n.id DESC
                    """,
                    tuple(params),
                )
                return list(cur.fetchall())
        finally:
            conn.close()

    def count_unread(self, user_id: int) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM notification_recipients WHERE user_id = %s AND status = %s",
                    (user_id, STATUS_UNREAD),
                )
                return int(cur.fetchone()["c"])
        finally:
            conn.close()

    def set_status(self, notification_id: int, user_id: int, status: str) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if status == STATUS_READ:
                    affected = cur.execute(
                        """
                        UPDATE notification_recipients
                        SET status = %s, read_at = COALESCE(read_at, %s)
                        WHERE notification_id = %s AND user_id = %s
                        """,
                        (status, now, notification_id, user_id),
                    )
                else:
                    affected = cur.execute(
                        """
                        UPDATE notification_recipients
                        SET status = %s, read_at = COALESCE(read_at, %s), closed_at = COALESCE(closed_at, %s)
                        WHERE notification_id = %s AND user_id = %s
                        """,
                        (status, now, now, notification_id, user_id),
                    )
            conn.commit()
        finally:
            conn.close()
        if affected <= 0:
            return None
        rows = self.list_for_user(user_id, include_closed=True)
        return next((r for r in rows if r["id"] == notification_id), None)

    def list_admin(self, created_by: Optional[int] = None) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                where = ""
                params = []
                if created_by is not None:
                    where = "WHERE n.created_by = %s"
                    params.append(created_by)
                cur.execute(
                    f"""
                    SELECT n.id, n.title, n.content, n.created_by, n.target_type, n.created_at,
                           COUNT(r.id) AS recipient_count,
                           SUM(CASE WHEN r.status = 'unread' THEN 1 ELSE 0 END) AS unread_count,
                           SUM(CASE WHEN r.status = 'read' THEN 1 ELSE 0 END) AS read_count,
                           SUM(CASE WHEN r.status = 'closed' THEN 1 ELSE 0 END) AS closed_count
                    FROM notifications n
                    LEFT JOIN notification_recipients r ON r.notification_id = n.id
                    {where}
                    GROUP BY n.id, n.title, n.content, n.created_by, n.target_type, n.created_at
                    ORDER BY n.created_at DESC, n.id DESC
                    """,
                    tuple(params),
                )
                return list(cur.fetchall())
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 仓库单例管理
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        if require_mysql():
            raise RuntimeError("生产环境必须启用 MySQL，不能使用内存通知仓库")
        logger.info("MYSQL_ENABLED=false，通知使用内存仓库（重启即失）。")
        return InMemoryNotificationRepo()
    try:
        repo = MySQLNotificationRepo()
        logger.info("通知已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        if require_mysql():
            raise RuntimeError(f"生产环境连接 MySQL 失败，通知仓库不可降级：{exc}") from exc
        logger.warning("接入 MySQL 失败，通知降级为内存仓库（重启即失）：%s", exc)
        return InMemoryNotificationRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def create_notification(
    created_by: int,
    title: str,
    content: str = "",
    target_user_ids: Optional[list[int]] = None,
    target_type: str = TARGET_USERS,
) -> dict:
    title = _validate_title(title)
    content = _validate_content(content)
    if target_type not in VALID_TARGETS:
        raise ValueError("通知范围不合法")
    user_ids = _dedupe_user_ids(target_user_ids or [])
    if not user_ids:
        raise ValueError("通知至少需要一个接收人")
    row = _get_repo().create(title, content, created_by, target_type, user_ids)
    return _admin_public(row)


def list_for_user(user_id: int, include_closed: bool = False) -> list[dict]:
    return [_user_public(r) for r in _get_repo().list_for_user(user_id, include_closed)]


def count_unread(user_id: int) -> int:
    return _get_repo().count_unread(user_id)


def mark_read(notification_id: int, user_id: int) -> Optional[dict]:
    row = _get_repo().set_status(notification_id, user_id, STATUS_READ)
    return _user_public(row) if row else None


def close(notification_id: int, user_id: int) -> Optional[dict]:
    row = _get_repo().set_status(notification_id, user_id, STATUS_CLOSED)
    return _user_public(row) if row else None


def list_admin(created_by: Optional[int] = None) -> list[dict]:
    return [_admin_public(r) for r in _get_repo().list_admin(created_by)]


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

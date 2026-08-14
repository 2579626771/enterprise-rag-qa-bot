"""聊天会话服务：把用户的问答会话与消息持久化到 MySQL。

替换早期前端 localStorage 占位（useSessions.ts），实现服务端持久化：
换浏览器/设备后历史仍在，且严格按用户隔离。

设计要点
--------
1. 两套仓库实现，接口一致：MySQLSessionRepo（真实落库）/ InMemorySessionRepo（降级+测试）。
2. 懒连接 + 自动降级：连不上 MySQL 时切换到内存仓库，不拖垮主流程。
3. 自动建表：CREATE TABLE IF NOT EXISTS（chat_sessions / chat_messages）。
4. 归属隔离：所有读/写都带 user_id 校验，用户 A 无法访问用户 B 的会话（返回 None/False）。

数据模型
--------
- 会话 chat_sessions：id / user_id / title / is_favorite / created_at / updated_at
- 消息 chat_messages：id / session_id / role / content / sources(JSON 文本) / created_at

对外模块级函数：list_sessions / create_session / rename_session / toggle_favorite /
delete_session / list_messages / append_message（均带 user_id 归属校验）。
"""

from __future__ import annotations

import json
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

logger = get_logger("session_service")


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _dump_sources(sources) -> str:
    """把来源列表序列化为 JSON 文本存储。空/异常时存空数组。"""
    try:
        return json.dumps(sources or [], ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


def _load_sources(raw) -> list:
    """把存储的 JSON 文本反序列化为列表。异常/空时返回空列表。"""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _dump_verdict(verdict) -> Optional[str]:
    """把研判结果 {answerable, reason, confidence} 序列化为 JSON 文本。空则存 NULL。"""
    if not verdict:
        return None
    try:
        return json.dumps(verdict, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _load_verdict(raw):
    """把存储的研判 JSON 文本反序列化为 dict。空/异常时返回 None（前端据此不显示徽标）。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        return None


def _session_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row.get("title") or "未命名会话",
        "is_favorite": bool(row.get("is_favorite")),
        "message_count": int(row.get("message_count") or 0),
        "created_at": _fmt_time(row.get("created_at")),
        "updated_at": _fmt_time(row.get("updated_at")),
    }


def _message_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "role": row.get("role") or "user",
        "content": row.get("content") or "",
        "sources": _load_sources(row.get("sources")),
        "verdict": _load_verdict(row.get("verdict")),
        "created_at": _fmt_time(row.get("created_at")),
    }


# ---------------------------------------------------------------------------
# 内存仓库：降级与测试用。会话/消息自增 id 由内部计数器模拟。
# ---------------------------------------------------------------------------
class InMemorySessionRepo:
    def __init__(self) -> None:
        self._sessions: dict[int, dict] = {}
        self._messages: dict[int, dict] = {}
        self._session_seq = 0
        self._message_seq = 0

    # ---- 会话 ----
    def list_sessions(self, user_id: int) -> list[dict]:
        rows = [r for r in self._sessions.values() if r["user_id"] == user_id]
        # 按更新时间倒序（最近的在前）
        rows.sort(key=lambda r: (r.get("updated_at") or r.get("created_at")), reverse=True)
        out = []
        for r in rows:
            count = sum(1 for m in self._messages.values() if m["session_id"] == r["id"])
            out.append(_session_public({**r, "message_count": count}))
        return out

    def create_session(self, user_id: int, title: str = "未命名会话") -> dict:
        self._session_seq += 1
        now = datetime.now()
        row = {
            "id": self._session_seq,
            "user_id": user_id,
            "title": title or "未命名会话",
            "is_favorite": False,
            "created_at": now,
            "updated_at": now,
        }
        self._sessions[row["id"]] = row
        return _session_public(row)

    def _owned(self, session_id: int, user_id: int) -> Optional[dict]:
        row = self._sessions.get(session_id)
        if row is None or row["user_id"] != user_id:
            return None
        return row

    def rename_session(self, session_id: int, user_id: int, title: str) -> Optional[dict]:
        row = self._owned(session_id, user_id)
        if row is None or not title.strip():
            return None
        row["title"] = title.strip()
        row["updated_at"] = datetime.now()
        return _session_public(row)

    def toggle_favorite(self, session_id: int, user_id: int) -> Optional[dict]:
        row = self._owned(session_id, user_id)
        if row is None:
            return None
        row["is_favorite"] = not row["is_favorite"]
        row["updated_at"] = datetime.now()
        return _session_public(row)

    def delete_session(self, session_id: int, user_id: int) -> bool:
        row = self._owned(session_id, user_id)
        if row is None:
            return False
        del self._sessions[session_id]
        for mid in [mid for mid, m in self._messages.items() if m["session_id"] == session_id]:
            del self._messages[mid]
        return True

    # ---- 消息 ----
    def list_messages(self, session_id: int, user_id: int) -> Optional[list[dict]]:
        if self._owned(session_id, user_id) is None:
            return None
        rows = [m for m in self._messages.values() if m["session_id"] == session_id]
        rows.sort(key=lambda m: m["id"])
        return [_message_public(m) for m in rows]

    def append_message(
        self,
        session_id: int,
        user_id: int,
        role: str,
        content: str,
        sources=None,
        verdict=None,
    ) -> Optional[dict]:
        row = self._owned(session_id, user_id)
        if row is None:
            return None
        self._message_seq += 1
        now = datetime.now()
        msg = {
            "id": self._message_seq,
            "session_id": session_id,
            "role": role,
            "content": content,
            "sources": _dump_sources(sources),
            "verdict": _dump_verdict(verdict),
            "created_at": now,
        }
        self._messages[msg["id"]] = msg
        # 追加消息即更新会话时间；若是首条 user 消息且标题仍为默认，用它更新标题。
        row["updated_at"] = now
        if role == "user" and row.get("title") in (None, "", "未命名会话"):
            row["title"] = content[:16] + "…" if len(content) > 16 else content
        return _message_public(msg)


# ---------------------------------------------------------------------------
# MySQL 仓库：真实落库。
# ---------------------------------------------------------------------------
_CREATE_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          INT          NOT NULL AUTO_INCREMENT,
    user_id     INT          NOT NULL,
    title       VARCHAR(255) NOT NULL DEFAULT '未命名会话',
    is_favorite TINYINT      NOT NULL DEFAULT 0,
    created_at  DATETIME     NOT NULL,
    updated_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id          INT          NOT NULL AUTO_INCREMENT,
    session_id  INT          NOT NULL,
    role        VARCHAR(16)  NOT NULL DEFAULT 'user',
    content     TEXT,
    sources     TEXT,
    verdict     TEXT,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLSessionRepo:
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
                cur.execute(_CREATE_SESSIONS_SQL)
                cur.execute(_CREATE_MESSAGES_SQL)
                # 存量表补列：早于「研判」上线建的 chat_messages 没有 verdict 列，
                # 这里检查缺失则补上（nullable，不影响存量数据）。与项目「自动建表/自动迁移」一致。
                cur.execute(
                    "SELECT COUNT(*) AS c FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'chat_messages' "
                    "AND column_name = 'verdict'",
                    (MYSQL_DATABASE,),
                )
                if (cur.fetchone() or {}).get("c", 0) == 0:
                    cur.execute("ALTER TABLE chat_messages ADD COLUMN verdict TEXT NULL AFTER sources")
            conn.commit()
        finally:
            conn.close()

    # ---- 会话 ----
    def list_sessions(self, user_id: int) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT s.id, s.title, s.is_favorite, s.created_at, s.updated_at, "
                    "(SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count "
                    "FROM chat_sessions s WHERE s.user_id = %s "
                    "ORDER BY s.updated_at DESC, s.id DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_session_public(r) for r in rows]

    def create_session(self, user_id: int, title: str = "未命名会话") -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_sessions (user_id, title, is_favorite, created_at, updated_at) "
                    "VALUES (%s, %s, 0, %s, %s)",
                    (user_id, title or "未命名会话", now, now),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return {
            "id": new_id,
            "title": title or "未命名会话",
            "is_favorite": False,
            "created_at": _fmt_time(now),
            "updated_at": _fmt_time(now),
        }

    def _get_owned_row(self, cur, session_id: int, user_id: int) -> Optional[dict]:
        cur.execute(
            "SELECT id, user_id, title, is_favorite, created_at, updated_at "
            "FROM chat_sessions WHERE id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None or row["user_id"] != user_id:
            return None
        return row

    def rename_session(self, session_id: int, user_id: int, title: str) -> Optional[dict]:
        if not title.strip():
            return None
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if self._get_owned_row(cur, session_id, user_id) is None:
                    return None
                cur.execute(
                    "UPDATE chat_sessions SET title = %s, updated_at = %s WHERE id = %s",
                    (title.strip(), now, session_id),
                )
                conn.commit()
                row = self._get_owned_row(cur, session_id, user_id)
        finally:
            conn.close()
        return _session_public(row) if row else None

    def toggle_favorite(self, session_id: int, user_id: int) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                row = self._get_owned_row(cur, session_id, user_id)
                if row is None:
                    return None
                new_fav = 0 if row["is_favorite"] else 1
                cur.execute(
                    "UPDATE chat_sessions SET is_favorite = %s, updated_at = %s WHERE id = %s",
                    (new_fav, now, session_id),
                )
                conn.commit()
                row = self._get_owned_row(cur, session_id, user_id)
        finally:
            conn.close()
        return _session_public(row) if row else None

    def delete_session(self, session_id: int, user_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if self._get_owned_row(cur, session_id, user_id) is None:
                    return False
                cur.execute("DELETE FROM chat_messages WHERE session_id = %s", (session_id,))
                cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
            conn.commit()
        finally:
            conn.close()
        return True

    # ---- 消息 ----
    def list_messages(self, session_id: int, user_id: int) -> Optional[list[dict]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if self._get_owned_row(cur, session_id, user_id) is None:
                    return None
                cur.execute(
                    "SELECT id, role, content, sources, verdict, created_at "
                    "FROM chat_messages WHERE session_id = %s ORDER BY id ASC",
                    (session_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_message_public(r) for r in rows]

    def append_message(
        self,
        session_id: int,
        user_id: int,
        role: str,
        content: str,
        sources=None,
        verdict=None,
    ) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                row = self._get_owned_row(cur, session_id, user_id)
                if row is None:
                    return None
                cur.execute(
                    "INSERT INTO chat_messages (session_id, role, content, sources, verdict, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (session_id, role, content, _dump_sources(sources), _dump_verdict(verdict), now),
                )
                new_id = cur.lastrowid
                # 更新会话时间；首条 user 消息且标题仍默认时用它更新标题。
                if role == "user" and (row.get("title") in (None, "", "未命名会话")):
                    new_title = content[:16] + "…" if len(content) > 16 else content
                    cur.execute(
                        "UPDATE chat_sessions SET title = %s, updated_at = %s WHERE id = %s",
                        (new_title, now, session_id),
                    )
                else:
                    cur.execute(
                        "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
                        (now, session_id),
                    )
            conn.commit()
        finally:
            conn.close()
        return {
            "id": new_id,
            "role": role,
            "content": content,
            "sources": _load_sources(_dump_sources(sources)),
            "verdict": _load_verdict(_dump_verdict(verdict)),
            "created_at": _fmt_time(now),
        }


# ---------------------------------------------------------------------------
# 仓库单例管理：懒初始化 + 失败降级。
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        logger.info("MYSQL_ENABLED=false，会话历史使用内存仓库（不落盘）。")
        return InMemorySessionRepo()
    try:
        repo = MySQLSessionRepo()
        logger.info("会话历史已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，降级为内存会话（仅不落盘，问答不受影响）：%s", exc)
        return InMemorySessionRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def list_sessions(user_id: int) -> list[dict]:
    """返回某用户的全部会话（最近更新在前）。"""
    return _get_repo().list_sessions(user_id)


def create_session(user_id: int, title: str = "未命名会话") -> dict:
    """为某用户新建一个会话。"""
    return _get_repo().create_session(user_id, title)


def rename_session(session_id: int, user_id: int, title: str) -> Optional[dict]:
    """改会话标题。非本人会话或标题为空返回 None。"""
    return _get_repo().rename_session(session_id, user_id, title)


def toggle_favorite(session_id: int, user_id: int) -> Optional[dict]:
    """切换收藏状态。非本人会话返回 None。"""
    return _get_repo().toggle_favorite(session_id, user_id)


def delete_session(session_id: int, user_id: int) -> bool:
    """删除会话及其消息。非本人会话返回 False。"""
    return _get_repo().delete_session(session_id, user_id)


def list_messages(session_id: int, user_id: int) -> Optional[list[dict]]:
    """返回会话内的消息列表（按时间正序）。非本人会话返回 None。"""
    return _get_repo().list_messages(session_id, user_id)


def append_message(
    session_id: int,
    user_id: int,
    role: str,
    content: str,
    sources=None,
    verdict=None,
) -> Optional[dict]:
    """向会话追加一条消息。非本人会话返回 None。"""
    return _get_repo().append_message(session_id, user_id, role, content, sources, verdict)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

"""用户服务：账号的持久化（MySQL）、密码哈希（bcrypt）、以及预置管理员。

沿用 metadata_service 的设计：
- MySQLUserRepo + InMemoryUserRepo 两套实现，接口一致；
- 懒连接 + 自动降级：MySQL 连不上时退回内存仓库（此时账号仅存活于进程内，
  重启即失，但保证登录/鉴权链路仍可跑，便于本地无库调试与单元测试）；
- 自动建 users 表；
- 提供 _set_repo_for_test / _reset_repo_for_test 供测试注入内存仓库。

对外模块级 API：
    create_user / register_user / authenticate / update_profile / change_password /
    reset_password / get_recovery_questions / reset_password_by_recovery /
    set_recovery_questions / get_by_username / get_by_id / list_all / delete / count
    verify_password(username, raw) -> user | None
    ensure_default_admin()
密码与找回问题答案只存 bcrypt 哈希，绝不存明文，返回给上层的 user dict 也不含 hash。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt

from app.config import (
    ADMIN_KB_QUOTA,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_KB_QUOTA,
    LOGIN_LOCK_MINUTES,
    LOGIN_MAX_FAILED_ATTEMPTS,
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from app.utils.logger import get_logger

logger = get_logger("user_service")

ROLE_ADMIN = "admin"
ROLE_USER = "user"

# 注册校验规则：
# 用户名——字母/数字/常见符号（_ . - @），不含空格与中文，长度 3-32。
# 密码——至少 8 位。
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-@]{3,32}$")
PASSWORD_MIN_LEN = 8
DISPLAY_NAME_MAX_LEN = 64
RECOVERY_QUESTION_COUNT = 3
RECOVERY_QUESTION_MAX_LEN = 255


class AccountLocked(Exception):
    """账号因连续登录失败被临时锁定。"""

    def __init__(self, locked_until) -> None:
        self.locked_until = locked_until
        super().__init__(f"账号已锁定，请在 {format_locked_until(locked_until)} 后再试，或联系管理员重置密码")


def validate_username(username: str) -> None:
    """校验用户名格式，不合法抛 ValueError。"""
    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if not USERNAME_PATTERN.match(username):
        raise ValueError("用户名只能包含字母、数字及 _ . - @，长度 3-32 位，且不含空格与中文")


def validate_password(password: str) -> None:
    """校验密码强度，不合法抛 ValueError。"""
    if not password or len(password) < PASSWORD_MIN_LEN:
        raise ValueError(f"密码至少 {PASSWORD_MIN_LEN} 位")


def validate_display_name(display_name: str) -> str:
    """校验并标准化显示名。"""
    value = (display_name or "").strip()
    if not value:
        raise ValueError("显示名不能为空")
    if len(value) > DISPLAY_NAME_MAX_LEN:
        raise ValueError(f"显示名不能超过 {DISPLAY_NAME_MAX_LEN} 个字符")
    return value


# ---- 密码 / 找回答案哈希工具 ----
def hash_password(raw: str) -> str:
    """把明文密码哈希成 bcrypt 字符串（自带随机 salt）。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(raw: str, hashed: str) -> bool:
    """校验明文与 bcrypt 哈希是否匹配。哈希损坏时安全返回 False。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def normalize_recovery_answer(answer: str) -> str:
    """找回答案标准化：去首尾空白、大小写不敏感，降低用户记忆成本。"""
    return (answer or "").strip().casefold()


def hash_recovery_answer(answer: str) -> str:
    return hash_password(normalize_recovery_answer(answer))


def check_recovery_answer(raw: str, hashed: str) -> bool:
    return check_password(normalize_recovery_answer(raw), hashed)


def _empty_recovery_values() -> dict:
    values = {}
    for i in range(1, RECOVERY_QUESTION_COUNT + 1):
        values[f"recovery_question_{i}"] = None
        values[f"recovery_answer_hash_{i}"] = None
    return values


def _has_recovery_questions(row: dict) -> bool:
    return all(
        row.get(f"recovery_question_{i}") and row.get(f"recovery_answer_hash_{i}")
        for i in range(1, RECOVERY_QUESTION_COUNT + 1)
    )


def _get_recovery_user_by_username(username: str) -> Optional[dict]:
    """找回密码只允许输入登录用户名，不允许用显示名找回。"""
    value = (username or "").strip()
    if not value:
        return None
    return _get_repo().get_by_username(value)


def _prepare_recovery_items(items) -> dict:
    """校验并转换 3 组找回问题答案，返回可直接写库的列值。"""
    if not isinstance(items, list) or len(items) != RECOVERY_QUESTION_COUNT:
        raise ValueError(f"请设置 {RECOVERY_QUESTION_COUNT} 个找回密码问题")
    values = _empty_recovery_values()
    for idx, item in enumerate(items, start=1):
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        question = (item.get("question") if isinstance(item, dict) else "") or ""
        answer = (item.get("answer") if isinstance(item, dict) else "") or ""
        question = question.strip()
        answer = answer.strip()
        if not question:
            raise ValueError(f"第 {idx} 个找回密码问题不能为空")
        if len(question) > RECOVERY_QUESTION_MAX_LEN:
            raise ValueError(f"第 {idx} 个找回密码问题不能超过 {RECOVERY_QUESTION_MAX_LEN} 个字符")
        if not answer:
            raise ValueError(f"第 {idx} 个找回密码答案不能为空")
        values[f"recovery_question_{idx}"] = question
        values[f"recovery_answer_hash_{idx}"] = hash_recovery_answer(answer)
    return values


def _public(row: dict) -> dict:
    """对外返回的用户视图：剔除 password_hash / 找回答案 hash，时间格式化。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row.get("role") or ROLE_USER,
        "display_name": row.get("display_name") or row["username"],
        "kb_quota": int(row.get("kb_quota") if row.get("kb_quota") is not None else DEFAULT_KB_QUOTA),
        "created_at": _fmt_time(row.get("created_at")),
        "last_login_at": _fmt_time(row.get("last_login_at")),
        "password_changed_at": _fmt_time(row.get("password_changed_at")),
        "force_password_change": bool(row.get("force_password_change")),
        "locked_until": _fmt_time(row.get("locked_until")) if _is_locked(row) else "—",
        "has_recovery_questions": _has_recovery_questions(row),
    }


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


def _parse_time(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _is_locked(row: dict) -> bool:
    locked_until = _parse_time(row.get("locked_until"))
    return locked_until is not None and locked_until > datetime.now()


def format_locked_until(value) -> str:
    return _fmt_time(value)


# ---------------------------------------------------------------------------
# 内存仓库：降级与测试用。
# ---------------------------------------------------------------------------
class InMemoryUserRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, dict] = {}
        self._seq = 0

    def create(
        self,
        username: str,
        password_hash: str,
        role: str,
        display_name: str,
        recovery_values: Optional[dict] = None,
    ) -> dict:
        if self._find_by_username(username) is not None:
            raise ValueError(f"用户名已存在：{username}")
        self._seq += 1
        now = datetime.now()
        quota = ADMIN_KB_QUOTA if role == ROLE_ADMIN else DEFAULT_KB_QUOTA
        row = {
            "id": self._seq,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "display_name": display_name,
            "kb_quota": quota,
            "failed_login_count": 0,
            "locked_until": None,
            "last_login_at": None,
            "password_changed_at": now,
            "force_password_change": False,
            "created_at": now,
            "updated_at": now,
            **_empty_recovery_values(),
        }
        row.update(recovery_values or {})
        self._by_id[self._seq] = row
        return dict(row)

    def get_by_username(self, username: str) -> Optional[dict]:
        row = self._find_by_username(username)
        return dict(row) if row else None

    def get_by_id(self, user_id: int) -> Optional[dict]:
        row = self._by_id.get(user_id)
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        return [dict(r) for r in sorted(self._by_id.values(), key=lambda r: r["id"])]

    def delete(self, user_id: int) -> bool:
        return self._by_id.pop(user_id, None) is not None

    def count(self, role: Optional[str] = None) -> int:
        if role is None:
            return len(self._by_id)
        return sum(1 for r in self._by_id.values() if r.get("role") == role)

    def update_quota(self, user_id: int, new_quota: int) -> bool:
        row = self._by_id.get(user_id)
        if not row:
            return False
        row["kb_quota"] = new_quota
        row["updated_at"] = datetime.now()
        return True

    def update_profile(self, user_id: int, display_name: str) -> Optional[dict]:
        row = self._by_id.get(user_id)
        if not row:
            return None
        row["display_name"] = display_name
        row["updated_at"] = datetime.now()
        return dict(row)

    def update_password(self, user_id: int, password_hash: str, force_password_change: bool) -> Optional[dict]:
        row = self._by_id.get(user_id)
        if not row:
            return None
        now = datetime.now()
        row["password_hash"] = password_hash
        row["password_changed_at"] = now
        row["force_password_change"] = bool(force_password_change)
        row["failed_login_count"] = 0
        row["locked_until"] = None
        row["updated_at"] = now
        return dict(row)

    def update_recovery_questions(self, user_id: int, recovery_values: dict) -> Optional[dict]:
        row = self._by_id.get(user_id)
        if not row:
            return None
        row.update(recovery_values)
        row["updated_at"] = datetime.now()
        return dict(row)

    def record_login_success(self, user_id: int) -> Optional[dict]:
        row = self._by_id.get(user_id)
        if not row:
            return None
        now = datetime.now()
        row["failed_login_count"] = 0
        row["locked_until"] = None
        row["last_login_at"] = now
        row["updated_at"] = now
        return dict(row)

    def record_login_failure(self, user_id: int, locked_until) -> Optional[dict]:
        row = self._by_id.get(user_id)
        if not row:
            return None
        row["failed_login_count"] = int(row.get("failed_login_count") or 0) + 1
        row["locked_until"] = locked_until
        row["updated_at"] = datetime.now()
        return dict(row)

    def _find_by_username(self, username: str) -> Optional[dict]:
        for row in self._by_id.values():
            if row["username"] == username:
                return row
        return None


# ---------------------------------------------------------------------------
# MySQL 仓库：真实落库。
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id                     INT          NOT NULL AUTO_INCREMENT,
    username               VARCHAR(64)  NOT NULL,
    password_hash          VARCHAR(255) NOT NULL,
    role                   VARCHAR(16)  NOT NULL DEFAULT 'user',
    display_name           VARCHAR(64),
    kb_quota               INT          NOT NULL DEFAULT 3,
    failed_login_count     INT          NOT NULL DEFAULT 0,
    locked_until           DATETIME,
    last_login_at          DATETIME,
    password_changed_at    DATETIME,
    force_password_change  TINYINT(1)   NOT NULL DEFAULT 0,
    recovery_question_1    VARCHAR(255),
    recovery_answer_hash_1 VARCHAR(255),
    recovery_question_2    VARCHAR(255),
    recovery_answer_hash_2 VARCHAR(255),
    recovery_question_3    VARCHAR(255),
    recovery_answer_hash_3 VARCHAR(255),
    created_at             DATETIME     NOT NULL,
    updated_at             DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_USER_COLUMNS = {
    "kb_quota": "ALTER TABLE users ADD COLUMN kb_quota INT NOT NULL DEFAULT 3",
    "failed_login_count": "ALTER TABLE users ADD COLUMN failed_login_count INT NOT NULL DEFAULT 0",
    "locked_until": "ALTER TABLE users ADD COLUMN locked_until DATETIME",
    "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
    "password_changed_at": "ALTER TABLE users ADD COLUMN password_changed_at DATETIME",
    "force_password_change": "ALTER TABLE users ADD COLUMN force_password_change TINYINT(1) NOT NULL DEFAULT 0",
    "recovery_question_1": "ALTER TABLE users ADD COLUMN recovery_question_1 VARCHAR(255)",
    "recovery_answer_hash_1": "ALTER TABLE users ADD COLUMN recovery_answer_hash_1 VARCHAR(255)",
    "recovery_question_2": "ALTER TABLE users ADD COLUMN recovery_question_2 VARCHAR(255)",
    "recovery_answer_hash_2": "ALTER TABLE users ADD COLUMN recovery_answer_hash_2 VARCHAR(255)",
    "recovery_question_3": "ALTER TABLE users ADD COLUMN recovery_question_3 VARCHAR(255)",
    "recovery_answer_hash_3": "ALTER TABLE users ADD COLUMN recovery_answer_hash_3 VARCHAR(255)",
}


class MySQLUserRepo:
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
                # 兼容旧库：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列。
                for column, alter_sql in _USER_COLUMNS.items():
                    cur.execute(
                        "SELECT COUNT(*) AS c FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = 'users' "
                        "AND column_name = %s",
                        (MYSQL_DATABASE, column),
                    )
                    if cur.fetchone()["c"] == 0:
                        cur.execute(alter_sql)
            conn.commit()
        finally:
            conn.close()

    def create(
        self,
        username: str,
        password_hash: str,
        role: str,
        display_name: str,
        recovery_values: Optional[dict] = None,
    ) -> dict:
        now = datetime.now()
        quota = ADMIN_KB_QUOTA if role == ROLE_ADMIN else DEFAULT_KB_QUOTA
        rv = {**_empty_recovery_values(), **(recovery_values or {})}
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 唯一约束保证用户名不重复；重复时 PyMySQL 抛 IntegrityError。
                if self._exists(cur, username):
                    raise ValueError(f"用户名已存在：{username}")
                cur.execute(
                    """
                    INSERT INTO users
                        (username, password_hash, role, display_name, kb_quota,
                         failed_login_count, locked_until, last_login_at, password_changed_at,
                         force_password_change,
                         recovery_question_1, recovery_answer_hash_1,
                         recovery_question_2, recovery_answer_hash_2,
                         recovery_question_3, recovery_answer_hash_3,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 0, NULL, NULL, %s, 0,
                            %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        password_hash,
                        role,
                        display_name,
                        quota,
                        now,
                        rv["recovery_question_1"],
                        rv["recovery_answer_hash_1"],
                        rv["recovery_question_2"],
                        rv["recovery_answer_hash_2"],
                        rv["recovery_question_3"],
                        rv["recovery_answer_hash_3"],
                        now,
                        now,
                    ),
                )
                new_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(new_id)

    @staticmethod
    def _exists(cur, username: str) -> bool:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        return cur.fetchone() is not None

    def get_by_username(self, username: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                return cur.fetchone()
        finally:
            conn.close()

    def get_by_id(self, user_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def list_all(self) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users ORDER BY id")
                return list(cur.fetchall())
        finally:
            conn.close()

    def delete(self, user_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
        finally:
            conn.close()
        return affected > 0

    def count(self, role: Optional[str] = None) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if role is None:
                    cur.execute("SELECT COUNT(*) AS c FROM users")
                else:
                    cur.execute("SELECT COUNT(*) AS c FROM users WHERE role = %s", (role,))
                return int(cur.fetchone()["c"])
        finally:
            conn.close()

    def update_quota(self, user_id: int, new_quota: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE users SET kb_quota = %s, updated_at = %s WHERE id = %s",
                    (new_quota, datetime.now(), user_id),
                )
            conn.commit()
        finally:
            conn.close()
        return affected > 0

    def update_profile(self, user_id: int, display_name: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE users SET display_name = %s, updated_at = %s WHERE id = %s",
                    (display_name, datetime.now(), user_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(user_id) if affected > 0 else None

    def update_password(self, user_id: int, password_hash: str, force_password_change: bool) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s,
                        password_changed_at = %s,
                        force_password_change = %s,
                        failed_login_count = 0,
                        locked_until = NULL,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (password_hash, now, 1 if force_password_change else 0, now, user_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(user_id) if affected > 0 else None

    def update_recovery_questions(self, user_id: int, recovery_values: dict) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE users
                    SET recovery_question_1 = %s,
                        recovery_answer_hash_1 = %s,
                        recovery_question_2 = %s,
                        recovery_answer_hash_2 = %s,
                        recovery_question_3 = %s,
                        recovery_answer_hash_3 = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        recovery_values["recovery_question_1"],
                        recovery_values["recovery_answer_hash_1"],
                        recovery_values["recovery_question_2"],
                        recovery_values["recovery_answer_hash_2"],
                        recovery_values["recovery_question_3"],
                        recovery_values["recovery_answer_hash_3"],
                        datetime.now(),
                        user_id,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(user_id) if affected > 0 else None

    def record_login_success(self, user_id: int) -> Optional[dict]:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE users
                    SET failed_login_count = 0,
                        locked_until = NULL,
                        last_login_at = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (now, now, user_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(user_id) if affected > 0 else None

    def record_login_failure(self, user_id: int, locked_until) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """
                    UPDATE users
                    SET failed_login_count = failed_login_count + 1,
                        locked_until = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (locked_until, datetime.now(), user_id),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_by_id(user_id) if affected > 0 else None


# ---------------------------------------------------------------------------
# 仓库单例管理：懒初始化 + 失败降级。
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        logger.info("MYSQL_ENABLED=false，用户账号使用内存仓库（重启即失）。")
        return InMemoryUserRepo()
    try:
        repo = MySQLUserRepo()
        logger.info("用户账号已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，用户账号降级为内存仓库（重启即失）：%s", exc)
        return InMemoryUserRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---- 对外模块级 API ----
def create_user(
    username: str,
    password: str,
    role: str = ROLE_USER,
    display_name: Optional[str] = None,
    recovery_items: Optional[list] = None,
) -> dict:
    """创建用户，返回不含密码哈希的公开视图。用户名重复会抛 ValueError。
    管理员创建用户时 recovery_items 可为空；用户登录后可在个人中心补设。"""
    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if not password:
        raise ValueError("密码不能为空")
    if role not in (ROLE_ADMIN, ROLE_USER):
        raise ValueError(f"非法角色：{role}")
    recovery_values = _prepare_recovery_items(recovery_items) if recovery_items is not None else None
    row = _get_repo().create(
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=(display_name or username).strip(),
        recovery_values=recovery_values,
    )
    return _public(row)


def register_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
    recovery_items: Optional[list] = None,
) -> dict:
    """自助注册：强制角色为普通用户，要求设置 3 组找回密码问题答案。"""
    username = (username or "").strip()
    validate_username(username)
    validate_password(password)
    recovery_values = _prepare_recovery_items(recovery_items)
    row = _get_repo().create(
        username=username,
        password_hash=hash_password(password),
        role=ROLE_USER,  # 注册只能是普通用户，写死不接受外部传入
        display_name=(display_name or username).strip(),
        recovery_values=recovery_values,
    )
    return _public(row)


def get_by_username(username: str) -> Optional[dict]:
    """按用户名取用户公开视图（不含密码哈希）。"""
    row = _get_repo().get_by_username(username)
    return _public(row) if row else None


def get_by_id(user_id: int) -> Optional[dict]:
    row = _get_repo().get_by_id(user_id)
    return _public(row) if row else None


def list_all() -> list[dict]:
    return [_public(r) for r in _get_repo().list_all()]


def delete(user_id: int) -> bool:
    return _get_repo().delete(user_id)


def count(role: Optional[str] = None) -> int:
    return _get_repo().count(role)


def get_quota(user_id: int) -> int:
    """取某用户的知识库配额上限。"""
    row = _get_repo().get_by_id(user_id)
    if not row:
        return 0
    return int(row.get("kb_quota") if row.get("kb_quota") is not None else DEFAULT_KB_QUOTA)


def increase_quota(user_id: int, amount: int) -> int:
    """在现有配额基础上增加 amount，返回新配额。用于配额申请通过。"""
    current = get_quota(user_id)
    new_quota = current + max(0, int(amount))
    _get_repo().update_quota(user_id, new_quota)
    return new_quota


def set_quota(user_id: int, new_quota: int) -> int:
    """直接设置某用户的知识库配额上限（管理员操作）。返回设置后的配额。
    new_quota 会被夹到 >= 0；用户不存在抛 ValueError。"""
    if get_by_id(user_id) is None:
        raise ValueError("用户不存在")
    new_quota = max(0, int(new_quota))
    _get_repo().update_quota(user_id, new_quota)
    return new_quota


def verify_password(username: str, raw_password: str) -> Optional[dict]:
    """纯账密校验：正确返回用户公开视图，否则返回 None；不记录登录成功/失败。"""
    row = _get_repo().get_by_username((username or "").strip())
    if not row:
        return None
    if not check_password(raw_password, row["password_hash"]):
        return None
    return _public(row)


def authenticate(username: str, raw_password: str) -> Optional[dict]:
    """登录认证：带失败计数、短时锁定、成功登录时间记录。"""
    repo = _get_repo()
    row = repo.get_by_username((username or "").strip())
    if not row:
        return None
    if _is_locked(row):
        raise AccountLocked(row.get("locked_until"))
    if not check_password(raw_password, row["password_hash"]):
        current_count = int(row.get("failed_login_count") or 0) + 1
        locked_until = None
        if LOGIN_MAX_FAILED_ATTEMPTS > 0 and current_count >= LOGIN_MAX_FAILED_ATTEMPTS:
            locked_until = datetime.now() + timedelta(minutes=max(1, LOGIN_LOCK_MINUTES))
        updated = repo.record_login_failure(row["id"], locked_until)
        if locked_until is not None:
            raise AccountLocked((updated or {}).get("locked_until") or locked_until)
        return None
    updated = repo.record_login_success(row["id"])
    return _public(updated or row)


def update_profile(user_id: int, display_name: str) -> dict:
    """修改当前用户显示名。"""
    display_name = validate_display_name(display_name)
    row = _get_repo().update_profile(user_id, display_name)
    if row is None:
        raise ValueError("用户不存在")
    return _public(row)


def change_password(user_id: int, old_password: str, new_password: str) -> dict:
    """用户修改自己的密码：需校验旧密码，成功后清除强制改密标记与锁定状态。"""
    validate_password(new_password)
    repo = _get_repo()
    row = repo.get_by_id(user_id)
    if row is None:
        raise ValueError("用户不存在")
    if not check_password(old_password, row["password_hash"]):
        raise ValueError("原密码不正确")
    updated = repo.update_password(user_id, hash_password(new_password), force_password_change=False)
    if updated is None:
        raise ValueError("用户不存在")
    return _public(updated)


def reset_password(user_id: int, new_password: str, force_password_change: bool = True) -> dict:
    """管理员重置用户密码。成功后清除失败计数/锁定状态，可要求下次登录后改密。"""
    validate_password(new_password)
    if get_by_id(user_id) is None:
        raise ValueError("用户不存在")
    updated = _get_repo().update_password(
        user_id,
        hash_password(new_password),
        force_password_change=force_password_change,
    )
    if updated is None:
        raise ValueError("用户不存在")
    return _public(updated)


def set_recovery_questions(user_id: int, recovery_items: list) -> dict:
    """当前用户设置/更新 3 组找回密码问题答案。"""
    recovery_values = _prepare_recovery_items(recovery_items)
    row = _get_repo().update_recovery_questions(user_id, recovery_values)
    if row is None:
        raise ValueError("用户不存在")
    return _public(row)


def get_recovery_questions(username: str) -> list[str]:
    """未登录找回密码第一步：按用户名返回 3 个问题文本，不返回答案。"""
    row = _get_recovery_user_by_username(username)
    if row is None or not _has_recovery_questions(row):
        raise ValueError("该登录用户名未设置找回问题或不存在，请联系管理员重置密码")
    return [row.get(f"recovery_question_{i}") or "" for i in range(1, RECOVERY_QUESTION_COUNT + 1)]


def reset_password_by_recovery(username: str, answers: list[str], new_password: str) -> dict:
    """未登录自助找回密码：三题全部答对后重置密码。"""
    validate_password(new_password)
    if not isinstance(answers, list) or len(answers) != RECOVERY_QUESTION_COUNT:
        raise ValueError(f"请回答 {RECOVERY_QUESTION_COUNT} 个找回密码问题")
    repo = _get_repo()
    row = _get_recovery_user_by_username(username)
    if row is None or not _has_recovery_questions(row):
        raise ValueError("该登录用户名未设置找回问题或不存在，请联系管理员重置密码")
    for idx, answer in enumerate(answers, start=1):
        if not check_recovery_answer(answer, row.get(f"recovery_answer_hash_{idx}")):
            raise ValueError("找回问题答案不正确")
    updated = repo.update_password(row["id"], hash_password(new_password), force_password_change=False)
    if updated is None:
        raise ValueError("用户不存在")
    return _public(updated)


def ensure_default_admin() -> None:
    """若系统中还没有任何管理员，则用配置里的默认账号创建一个。幂等。"""
    try:
        if _get_repo().count(ROLE_ADMIN) > 0:
            return
        create_user(
            username=DEFAULT_ADMIN_USERNAME,
            password=DEFAULT_ADMIN_PASSWORD,
            role=ROLE_ADMIN,
            display_name="系统管理员",
        )
        logger.info("已预置默认管理员账号：%s", DEFAULT_ADMIN_USERNAME)
    except Exception as exc:
        # 预置失败不应阻断服务启动（例如并发下唯一约束冲突）。
        logger.warning("预置默认管理员失败（可忽略，通常表示已存在）：%s", exc)


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

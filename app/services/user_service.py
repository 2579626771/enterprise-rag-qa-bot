"""用户服务：账号的持久化（MySQL）、密码哈希（bcrypt）、以及预置管理员。

沿用 metadata_service 的设计：
- MySQLUserRepo + InMemoryUserRepo 两套实现，接口一致；
- 懒连接 + 自动降级：MySQL 连不上时退回内存仓库（此时账号仅存活于进程内，
  重启即失，但保证登录/鉴权链路仍可跑，便于本地无库调试与单元测试）；
- 自动建 users 表；
- 提供 _set_repo_for_test / _reset_repo_for_test 供测试注入内存仓库。

对外模块级 API：
    create_user / get_by_username / get_by_id / list_all / delete / count
    verify_password(username, raw) -> user | None
    ensure_default_admin()
密码只存 bcrypt 哈希，绝不存明文，返回给上层的 user dict 也不含 password_hash。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import bcrypt

from app.config import (
    ADMIN_KB_QUOTA,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_KB_QUOTA,
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



# ---- 密码哈希工具 ----
def hash_password(raw: str) -> str:
    """把明文密码哈希成 bcrypt 字符串（自带随机 salt）。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(raw: str, hashed: str) -> bool:
    """校验明文与 bcrypt 哈希是否匹配。哈希损坏时安全返回 False。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _public(row: dict) -> dict:
    """对外返回的用户视图：剔除 password_hash，时间格式化。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row.get("role") or ROLE_USER,
        "display_name": row.get("display_name") or row["username"],
        "kb_quota": int(row.get("kb_quota") if row.get("kb_quota") is not None else DEFAULT_KB_QUOTA),
        "created_at": _fmt_time(row.get("created_at")),
    }


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    if isinstance(value, str) and value:
        return value
    return "—"


# ---------------------------------------------------------------------------
# 内存仓库：降级与测试用。
# ---------------------------------------------------------------------------
class InMemoryUserRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, dict] = {}
        self._seq = 0

    def create(self, username: str, password_hash: str, role: str, display_name: str) -> dict:
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
            "created_at": now,
            "updated_at": now,
        }
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
    id            INT          NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(16)  NOT NULL DEFAULT 'user',
    display_name  VARCHAR(64),
    kb_quota      INT          NOT NULL DEFAULT 3,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


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
                # 兼容旧库：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
                # 这里显式检查 kb_quota 是否存在，缺则 ALTER 补上。
                cur.execute(
                    "SELECT COUNT(*) AS c FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'users' "
                    "AND column_name = 'kb_quota'",
                    (MYSQL_DATABASE,),
                )
                if cur.fetchone()["c"] == 0:
                    cur.execute(
                        "ALTER TABLE users ADD COLUMN kb_quota INT NOT NULL DEFAULT 3"
                    )
            conn.commit()
        finally:
            conn.close()

    def create(self, username: str, password_hash: str, role: str, display_name: str) -> dict:
        now = datetime.now()
        quota = ADMIN_KB_QUOTA if role == ROLE_ADMIN else DEFAULT_KB_QUOTA
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 唯一约束保证用户名不重复；重复时 PyMySQL 抛 IntegrityError。
                if self._exists(cur, username):
                    raise ValueError(f"用户名已存在：{username}")
                cur.execute(
                    """
                    INSERT INTO users
                        (username, password_hash, role, display_name, kb_quota, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (username, password_hash, role, display_name, quota, now, now),
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
) -> dict:
    """创建用户，返回不含密码哈希的公开视图。用户名重复会抛 ValueError。"""
    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if not password:
        raise ValueError("密码不能为空")
    if role not in (ROLE_ADMIN, ROLE_USER):
        raise ValueError(f"非法角色：{role}")
    row = _get_repo().create(
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=(display_name or username).strip(),
    )
    return _public(row)


def register_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
) -> dict:
    """自助注册：强制角色为普通用户（不可注册管理员），并做格式校验。
    用户名规则见 validate_username，密码至少 8 位。用户名重复抛 ValueError。"""
    username = (username or "").strip()
    validate_username(username)
    validate_password(password)
    row = _get_repo().create(
        username=username,
        password_hash=hash_password(password),
        role=ROLE_USER,  # 注册只能是普通用户，写死不接受外部传入
        display_name=(display_name or username).strip(),
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


def verify_password(username: str, raw_password: str) -> Optional[dict]:
    """校验登录：账密正确返回用户公开视图，否则返回 None。"""
    row = _get_repo().get_by_username((username or "").strip())
    if not row:
        return None
    if not check_password(raw_password, row["password_hash"]):
        return None
    return _public(row)


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

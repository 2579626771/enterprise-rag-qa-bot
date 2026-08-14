"""检索配置服务：三级检索参数（系统/租户/知识库）的持久化与有效值解析。

阶段5「检索配置页」的后端骨架。让 top_k / 相似度阈值 / 研判开关 / 作答提示词
可在线调整、存 MySQL，而不必改 .env 重启后端。

三级配置层次（scope）：
  - system：全系统兜底默认（仅管理员可改）。
  - tenant：某用户对自己所有库的默认（含 multi_scope 偏好：多/全库查询用哪份配置）。
  - kb    ：某用户对自己某一个知识库的独立配置（各库独立）。

有效值解析 resolve_effective(owner_id, kb_id)：
  - 单库查询（kb_id 给定）：kb 行 → tenant 行 → system 行 → 硬默认，取第一个存在的整行。
  - 多/全库查询（kb_id=None）：读该 tenant 行的 multi_scope（默认 'system'）：
      'tenant' → tenant 行 → system 行 → 硬默认
      'system' → system 行 → 硬默认

关键：rag_service 把 RAG_TOP_K/RAG_MAX_DISTANCE/JUDGE_ENABLED 绑成了 import-time 模块常量
快照，光写库不会生效。故本服务只负责「解析出有效值」，由 /rag/ask 取值后显式传给
answer_from_knowledge_base（top_k 早已是入参，这里把其余三项也做成入参）。

沿用 kb_service / user_service 的双仓库 + 懒连接 + 降级 + _set_repo_for_test 模式。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import (
    JUDGE_ENABLED,
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    RAG_MAX_DISTANCE,
    RAG_TOP_K,
)
from app.utils.logger import get_logger

logger = get_logger("retrieval_config_service")

SCOPE_SYSTEM = "system"
SCOPE_TENANT = "tenant"
SCOPE_KB = "kb"
_VALID_SCOPES = {SCOPE_SYSTEM, SCOPE_TENANT, SCOPE_KB}

# multi_scope（仅 tenant 行有意义）：多/全库查询用哪份配置。
MULTI_SYSTEM = "system"
MULTI_TENANT = "tenant"
_VALID_MULTI = {MULTI_SYSTEM, MULTI_TENANT}


def _hard_defaults() -> dict:
    """无任何配置行时的硬兜底：读 config 常量 + answer_service 默认作答提示词。

    在函数内 import answer_service 避免模块级循环依赖（answer_service 未反向依赖本模块，
    但保持与 kb_service 里「延迟导入 topic_service」一致的防御习惯）。
    """
    from app.services.answer_service import DEFAULT_ANSWER_PROMPT

    return {
        "top_k": int(RAG_TOP_K),
        "max_distance": float(RAG_MAX_DISTANCE),
        "judge_enabled": bool(JUDGE_ENABLED),
        "answer_prompt": DEFAULT_ANSWER_PROMPT,
    }


def _values(row: Optional[dict]) -> Optional[dict]:
    """从一行配置里抽出 4 个有效字段（不含 scope/owner/kb/multi_scope 等元信息）。"""
    if not row:
        return None
    return {
        "top_k": int(row["top_k"]),
        "max_distance": float(row["max_distance"]),
        "judge_enabled": bool(row["judge_enabled"]),
        "answer_prompt": row.get("answer_prompt") or "",
    }


def _public(row: Optional[dict], *, inherited: bool = False) -> Optional[dict]:
    """对外视图：值字段 + inherited 标记（True 表示该级无自有行、展示的是继承/兜底值）。"""
    if row is None:
        return None
    out = {
        "top_k": int(row["top_k"]),
        "max_distance": float(row["max_distance"]),
        "judge_enabled": bool(row["judge_enabled"]),
        "answer_prompt": row.get("answer_prompt") or "",
        "inherited": inherited,
    }
    if row.get("multi_scope") is not None:
        out["multi_scope"] = row["multi_scope"]
    return out


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryConfigRepo:
    """按 (scope, owner_id, kb_id) 唯一存一行。owner_id/kb_id 用 None 表示不适用。"""

    def __init__(self) -> None:
        self._by_key: dict[tuple, dict] = {}
        self._seq = 0

    @staticmethod
    def _key(scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> tuple:
        return (scope, owner_id, kb_id)

    def get(self, scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> Optional[dict]:
        row = self._by_key.get(self._key(scope, owner_id, kb_id))
        return dict(row) if row else None

    def upsert(
        self,
        scope: str,
        owner_id: Optional[int],
        kb_id: Optional[int],
        top_k: int,
        max_distance: float,
        judge_enabled: bool,
        answer_prompt: str,
        multi_scope: Optional[str],
    ) -> dict:
        key = self._key(scope, owner_id, kb_id)
        now = datetime.now()
        existing = self._by_key.get(key)
        if existing:
            existing.update(
                {
                    "top_k": top_k,
                    "max_distance": max_distance,
                    "judge_enabled": judge_enabled,
                    "answer_prompt": answer_prompt,
                    "multi_scope": multi_scope,
                    "updated_at": now,
                }
            )
            return dict(existing)
        self._seq += 1
        row = {
            "id": self._seq,
            "scope": scope,
            "owner_id": owner_id,
            "kb_id": kb_id,
            "top_k": top_k,
            "max_distance": max_distance,
            "judge_enabled": judge_enabled,
            "answer_prompt": answer_prompt,
            "multi_scope": multi_scope,
            "updated_at": now,
        }
        self._by_key[key] = row
        return dict(row)

    def delete(self, scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> bool:
        return self._by_key.pop(self._key(scope, owner_id, kb_id), None) is not None


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS retrieval_configs (
    id            INT          NOT NULL AUTO_INCREMENT,
    scope         VARCHAR(16)  NOT NULL,
    owner_id      INT          NULL,
    kb_id         INT          NULL,
    top_k         INT          NOT NULL,
    max_distance  DOUBLE       NOT NULL,
    judge_enabled TINYINT(1)   NOT NULL,
    answer_prompt TEXT         NULL,
    multi_scope   VARCHAR(16)  NULL,
    updated_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_scope (scope, owner_id, kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLConfigRepo:
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

    def get(self, scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # <=> 为 NULL 安全等值比较：owner_id/kb_id 可能为 NULL，普通 = 匹配不到。
                cur.execute(
                    "SELECT * FROM retrieval_configs "
                    "WHERE scope = %s AND owner_id <=> %s AND kb_id <=> %s",
                    (scope, owner_id, kb_id),
                )
                return cur.fetchone()
        finally:
            conn.close()

    def upsert(
        self,
        scope: str,
        owner_id: Optional[int],
        kb_id: Optional[int],
        top_k: int,
        max_distance: float,
        judge_enabled: bool,
        answer_prompt: str,
        multi_scope: Optional[str],
    ) -> dict:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 手工 upsert（先查后写）：唯一键含 NULL 列，MySQL 对 NULL 视为互不相等，
                # 不能依赖 INSERT ... ON DUPLICATE KEY；故显式判断存在与否。
                cur.execute(
                    "SELECT id FROM retrieval_configs "
                    "WHERE scope = %s AND owner_id <=> %s AND kb_id <=> %s",
                    (scope, owner_id, kb_id),
                )
                found = cur.fetchone()
                if found:
                    cur.execute(
                        "UPDATE retrieval_configs SET "
                        "top_k=%s, max_distance=%s, judge_enabled=%s, "
                        "answer_prompt=%s, multi_scope=%s, updated_at=%s "
                        "WHERE id=%s",
                        (
                            top_k,
                            max_distance,
                            1 if judge_enabled else 0,
                            answer_prompt,
                            multi_scope,
                            now,
                            found["id"],
                        ),
                    )
                else:
                    cur.execute(
                        "INSERT INTO retrieval_configs "
                        "(scope, owner_id, kb_id, top_k, max_distance, judge_enabled, "
                        " answer_prompt, multi_scope, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            scope,
                            owner_id,
                            kb_id,
                            top_k,
                            max_distance,
                            1 if judge_enabled else 0,
                            answer_prompt,
                            multi_scope,
                            now,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        return self.get(scope, owner_id, kb_id)

    def delete(self, scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "DELETE FROM retrieval_configs "
                    "WHERE scope = %s AND owner_id <=> %s AND kb_id <=> %s",
                    (scope, owner_id, kb_id),
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
        logger.info("MYSQL_ENABLED=false，检索配置使用内存仓库（重启即失）。")
        return InMemoryConfigRepo()
    try:
        repo = MySQLConfigRepo()
        logger.info("检索配置已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:
        logger.warning("接入 MySQL 失败，检索配置降级为内存仓库（重启即失）：%s", exc)
        return InMemoryConfigRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


# ---------------------------------------------------------------------------
# 校验/规整
# ---------------------------------------------------------------------------
def _normalize(top_k, max_distance, judge_enabled, answer_prompt) -> dict:
    """把入参规整成合法值（防御性；api 层 pydantic 已做主要范围校验）。"""
    tk = int(top_k)
    if tk < 1 or tk > 20:
        raise ValueError("top_k 必须在 1~20 之间")
    md = float(max_distance)
    if md < 0 or md > 1:
        raise ValueError("max_distance 必须在 0~1 之间")
    return {
        "top_k": tk,
        "max_distance": md,
        "judge_enabled": bool(judge_enabled),
        "answer_prompt": (answer_prompt or "").strip(),
    }


# ---------------------------------------------------------------------------
# 对外模块级 API
# ---------------------------------------------------------------------------
def get_system() -> Optional[dict]:
    return _get_repo().get(SCOPE_SYSTEM, None, None)


def set_system(top_k, max_distance, judge_enabled, answer_prompt) -> dict:
    v = _normalize(top_k, max_distance, judge_enabled, answer_prompt)
    return _get_repo().upsert(
        SCOPE_SYSTEM, None, None,
        v["top_k"], v["max_distance"], v["judge_enabled"], v["answer_prompt"],
        multi_scope=None,
    )


def get_tenant(owner_id: int) -> Optional[dict]:
    return _get_repo().get(SCOPE_TENANT, owner_id, None)


def set_tenant(owner_id, top_k, max_distance, judge_enabled, answer_prompt, multi_scope) -> dict:
    v = _normalize(top_k, max_distance, judge_enabled, answer_prompt)
    ms = multi_scope if multi_scope in _VALID_MULTI else MULTI_SYSTEM
    return _get_repo().upsert(
        SCOPE_TENANT, owner_id, None,
        v["top_k"], v["max_distance"], v["judge_enabled"], v["answer_prompt"],
        multi_scope=ms,
    )


def get_kb(kb_id: int) -> Optional[dict]:
    return _get_repo().get(SCOPE_KB, None, kb_id)


def set_kb(kb_id, owner_id, top_k, max_distance, judge_enabled, answer_prompt) -> dict:
    """某知识库的独立配置。

    kb_id 全局唯一（知识库主键），故 kb 级配置行按 kb_id 单独定位（repo key 里 owner_id=None，
    与 get_kb/clear_kb 一致）。owner_id 参数仅用于 api 层已做的隔离校验，不参与存储键。
    """
    v = _normalize(top_k, max_distance, judge_enabled, answer_prompt)
    return _get_repo().upsert(
        SCOPE_KB, None, kb_id,
        v["top_k"], v["max_distance"], v["judge_enabled"], v["answer_prompt"],
        multi_scope=None,
    )


def clear_kb(kb_id: int) -> bool:
    """清除某知识库的独立配置，回落继承（tenant/system/硬默认）。"""
    return _get_repo().delete(SCOPE_KB, None, kb_id)


def get_multi_scope(owner_id: int) -> str:
    """该用户「多/全库查询用哪份配置」的偏好；无 tenant 行时默认 'system'。"""
    row = get_tenant(owner_id)
    ms = (row or {}).get("multi_scope")
    return ms if ms in _VALID_MULTI else MULTI_SYSTEM


def get_view(scope: str, owner_id: Optional[int], kb_id: Optional[int]) -> dict:
    """供前端配置页读取：返回该级的配置值 + inherited 标记。

    有自有行 → 返回自有值（inherited=False）。
    无自有行 → 返回「该级若无覆盖时会继承到的值」（inherited=True），便于前端展示当前生效值：
      - system 无行 → 硬默认
      - tenant 无行 → system 行 → 硬默认
      - kb     无行 → tenant 行 → system 行 → 硬默认
    tenant 级附带 multi_scope（无行时给默认 'system'）。
    """
    if scope == SCOPE_SYSTEM:
        own = get_system()
        if own:
            return _public(own, inherited=False)
        d = _hard_defaults()
        return {**d, "inherited": True}

    if scope == SCOPE_TENANT:
        own = get_tenant(owner_id)
        if own:
            return _public(own, inherited=False)
        vals = _values(get_system()) or _hard_defaults()
        return {**vals, "multi_scope": MULTI_SYSTEM, "inherited": True}

    if scope == SCOPE_KB:
        own = get_kb(kb_id)
        if own:
            return _public(own, inherited=False)
        chain = [get_tenant(owner_id) if owner_id is not None else None, get_system()]
        vals = None
        for row in chain:
            vals = _values(row)
            if vals is not None:
                break
        vals = vals or _hard_defaults()
        return {**vals, "inherited": True}

    raise ValueError(f"未知 scope：{scope}")


def resolve_effective(owner_id: Optional[int], kb_id: Optional[int]) -> dict:
    """解析出实际生效的检索参数（4 字段），供 /rag/ask 显式传给 rag_service。

    单库（kb_id 非空）：kb 行 → tenant 行 → system 行 → 硬默认（取第一个存在的整行）。
    多/全库（kb_id=None）：按 tenant 的 multi_scope 偏好：
        'tenant' → tenant 行 → system 行 → 硬默认
        'system' → system 行 → 硬默认
    """
    if kb_id is not None:
        chain = [
            get_kb(kb_id),
            get_tenant(owner_id) if owner_id is not None else None,
            get_system(),
        ]
    else:
        prefer_tenant = (
            owner_id is not None and get_multi_scope(owner_id) == MULTI_TENANT
        )
        if prefer_tenant:
            chain = [get_tenant(owner_id), get_system()]
        else:
            chain = [get_system()]

    for row in chain:
        vals = _values(row)
        if vals is not None:
            return vals
    return _hard_defaults()


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

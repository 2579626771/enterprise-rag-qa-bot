"""模型调用用量监控服务。

记录向量模型、问答/研判大模型、查询改写与 rerank 的调用情况，用于管理员侧查看：
调用次数、token 消耗、平均延迟、失败率和异常告警。

设计原则：
1. 沿用项目已有的“双仓库 + MySQL 自动建表 + 内存降级”模式。
2. 监控绝不能影响主业务：记录失败只写日志，不向上抛。
3. 用 contextvars 保存当前 user_id/kb_id/request_id，避免把用户归因参数层层传入所有模型函数。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Optional

from app.config import (
    MODEL_USAGE_ALERT_ERROR_RATE,
    MODEL_USAGE_ALERT_LATENCY_CHAT_MS,
    MODEL_USAGE_ALERT_LATENCY_EMBEDDING_MS,
    MODEL_USAGE_ALERT_LATENCY_RERANK_MS,
    MODEL_USAGE_ALERT_MIN_CALLS,
    MODEL_USAGE_ALERT_TOKEN_DAILY,
    MYSQL_DATABASE,
    MYSQL_ENABLED,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    require_mysql,
)
from app.utils.logger import get_logger

logger = get_logger("model_usage_service")

MODEL_EMBEDDING = "embedding"
MODEL_CHAT = "chat"
MODEL_JUDGE = "judge"
MODEL_QUERY_REWRITE = "query_rewrite"
MODEL_RERANK = "rerank"
VALID_MODEL_TYPES = {
    MODEL_EMBEDDING,
    MODEL_CHAT,
    MODEL_JUDGE,
    MODEL_QUERY_REWRITE,
    MODEL_RERANK,
}

_context: ContextVar[dict] = ContextVar("model_usage_context", default={})


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M:%S")
    if isinstance(value, str) and value:
        return value
    return "—"


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return datetime.now()


def _clip(value: str, limit: int = 500) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[:limit]


@contextmanager
def usage_context(
    user_id: int | None = None,
    kb_id: int | None = None,
    request_id: str | None = None,
    operation: str | None = None,
):
    """设置当前模型调用归因上下文。

    嵌套时只覆盖显式传入的字段，未传字段继承外层上下文。
    """
    parent = dict(_context.get() or {})
    current = dict(parent)
    if user_id is not None:
        current["user_id"] = user_id
    if kb_id is not None:
        current["kb_id"] = kb_id
    if request_id is not None:
        current["request_id"] = request_id
    if operation is not None:
        current["operation"] = operation
    token = _context.set(current)
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict:
    return dict(_context.get() or {})


# ---------------------------------------------------------------------------
# usage 解析
# ---------------------------------------------------------------------------
def extract_usage(payload) -> dict:
    """从不同厂商响应里尽量提取 token usage，取不到则返回 0。"""
    usage = {}
    if isinstance(payload, dict):
        usage = payload.get("usage") or payload.get("output", {}).get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    prompt = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("input_token_count", 0)))
    completion = usage.get("completion_tokens", usage.get("output_tokens", usage.get("output_token_count", 0)))
    total = usage.get("total_tokens", usage.get("total_token_count", 0))

    try:
        prompt = int(prompt or 0)
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = int(completion or 0)
    except (TypeError, ValueError):
        completion = 0
    try:
        total = int(total or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        total = prompt + completion
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def extract_langchain_usage(response) -> dict:
    """从 LangChain AIMessage 尽量提取 token usage。"""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        prompt = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        completion = usage.get("output_tokens", usage.get("completion_tokens", 0))
        total = usage.get("total_tokens", 0) or (int(prompt or 0) + int(completion or 0))
        return {
            "prompt_tokens": int(prompt or 0),
            "completion_tokens": int(completion or 0),
            "total_tokens": int(total or 0),
        }

    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        return extract_usage({"usage": metadata.get("token_usage") or metadata.get("usage") or {}})
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _public(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "kb_id": row.get("kb_id"),
        "request_id": row.get("request_id") or "",
        "model_type": row.get("model_type") or "",
        "provider": row.get("provider") or "",
        "model_name": row.get("model_name") or "",
        "operation": row.get("operation") or "",
        "success": bool(row.get("success")),
        "latency_ms": int(row.get("latency_ms") or 0),
        "prompt_tokens": int(row.get("prompt_tokens") or 0),
        "completion_tokens": int(row.get("completion_tokens") or 0),
        "total_tokens": int(row.get("total_tokens") or 0),
        "input_count": int(row.get("input_count") or 0),
        "error_type": row.get("error_type") or "",
        "error_message": row.get("error_message") or "",
        "created_at": _fmt_time(row.get("created_at")),
    }


# ---------------------------------------------------------------------------
# 内存仓库
# ---------------------------------------------------------------------------
class InMemoryModelUsageRepo:
    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._seq = 0

    def add(self, row: dict) -> dict:
        self._seq += 1
        stored = dict(row)
        stored["id"] = self._seq
        self._rows.append(stored)
        return dict(stored)

    def list_records(
        self,
        since: datetime,
        user_id: Optional[int] = None,
        model_type: Optional[str] = None,
        success: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        rows = []
        for row in self._rows:
            created_at = _to_datetime(row.get("created_at"))
            if created_at < since:
                continue
            if user_id is not None and row.get("user_id") != user_id:
                continue
            if model_type and row.get("model_type") != model_type:
                continue
            if success is not None and bool(row.get("success")) != success:
                continue
            rows.append(dict(row))
        rows.sort(key=lambda r: (_to_datetime(r.get("created_at")), int(r.get("id") or 0)), reverse=True)
        return rows[:limit] if limit else rows


# ---------------------------------------------------------------------------
# MySQL 仓库
# ---------------------------------------------------------------------------
_CREATE_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS model_usage_records (
    id                INT          NOT NULL AUTO_INCREMENT,
    user_id           INT          NULL,
    kb_id             INT          NULL,
    request_id        VARCHAR(64)  NOT NULL DEFAULT '',
    model_type        VARCHAR(32)  NOT NULL,
    provider          VARCHAR(32)  NOT NULL,
    model_name        VARCHAR(128) NOT NULL,
    operation         VARCHAR(64)  NOT NULL,
    success           TINYINT(1)   NOT NULL,
    latency_ms        INT          NOT NULL DEFAULT 0,
    prompt_tokens     INT          NOT NULL DEFAULT 0,
    completion_tokens INT          NOT NULL DEFAULT 0,
    total_tokens      INT          NOT NULL DEFAULT 0,
    input_count       INT          NOT NULL DEFAULT 0,
    error_type        VARCHAR(120) NOT NULL DEFAULT '',
    error_message     VARCHAR(500) NOT NULL DEFAULT '',
    created_at        DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_created (created_at),
    KEY idx_user_created (user_id, created_at),
    KEY idx_model_created (model_type, created_at),
    KEY idx_success_created (success, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLModelUsageRepo:
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
                cur.execute(_CREATE_USAGE_SQL)
            conn.commit()
        finally:
            conn.close()

    def add(self, row: dict) -> dict:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_usage_records
                        (user_id, kb_id, request_id, model_type, provider, model_name, operation,
                         success, latency_ms, prompt_tokens, completion_tokens, total_tokens,
                         input_count, error_type, error_message, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.get("user_id"),
                        row.get("kb_id"),
                        row.get("request_id") or "",
                        row.get("model_type") or "",
                        row.get("provider") or "",
                        row.get("model_name") or "",
                        row.get("operation") or "",
                        1 if row.get("success") else 0,
                        int(row.get("latency_ms") or 0),
                        int(row.get("prompt_tokens") or 0),
                        int(row.get("completion_tokens") or 0),
                        int(row.get("total_tokens") or 0),
                        int(row.get("input_count") or 0),
                        row.get("error_type") or "",
                        row.get("error_message") or "",
                        row.get("created_at") or datetime.now(),
                    ),
                )
                row_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        stored = dict(row)
        stored["id"] = row_id
        return stored

    def list_records(
        self,
        since: datetime,
        user_id: Optional[int] = None,
        model_type: Optional[str] = None,
        success: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        clauses = ["created_at >= %s"]
        params: list = [since]
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        if model_type:
            clauses.append("model_type = %s")
            params.append(model_type)
        if success is not None:
            clauses.append("success = %s")
            params.append(1 if success else 0)
        where = " AND ".join(clauses)
        limit_sql = " LIMIT %s" if limit else ""
        if limit:
            params.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT * FROM model_usage_records
                    WHERE {where}
                    ORDER BY created_at DESC, id DESC
                    {limit_sql}
                    """,
                    tuple(params),
                )
                return list(cur.fetchall())
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 仓库单例
# ---------------------------------------------------------------------------
_repo = None


def _build_repo():
    if not MYSQL_ENABLED:
        if require_mysql():
            raise RuntimeError("生产环境必须启用 MySQL，不能使用内存模型用量仓库")
        logger.info("MYSQL_ENABLED=false，模型用量监控使用内存仓库（重启即失）。")
        return InMemoryModelUsageRepo()
    try:
        repo = MySQLModelUsageRepo()
        logger.info("模型用量监控已接入 MySQL：%s:%s/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)
        return repo
    except Exception as exc:  # noqa: BLE001
        if require_mysql():
            raise RuntimeError(f"生产环境连接 MySQL 失败，模型用量仓库不可降级：{exc}") from exc
        logger.warning("接入 MySQL 失败，模型用量监控降级为内存仓库（重启即失）：%s", exc)
        return InMemoryModelUsageRepo()


def _get_repo():
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


def record_call(
    model_type: str,
    provider: str,
    model_name: str,
    operation: str | None = None,
    success: bool = True,
    latency_ms: int | float = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    input_count: int = 1,
    error_type: str = "",
    error_message: str = "",
    user_id: int | None = None,
    kb_id: int | None = None,
    request_id: str | None = None,
) -> Optional[dict]:
    """记录一次模型调用。记录失败不会影响业务主流程。"""
    try:
        ctx = current_context()
        if user_id is None:
            user_id = ctx.get("user_id")
        if kb_id is None:
            kb_id = ctx.get("kb_id")
        if request_id is None:
            request_id = ctx.get("request_id")
        if operation is None:
            operation = ctx.get("operation") or ""
        if model_type not in VALID_MODEL_TYPES:
            model_type = str(model_type or "unknown")
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        row = {
            "user_id": user_id,
            "kb_id": kb_id,
            "request_id": request_id or "",
            "model_type": model_type,
            "provider": provider or "",
            "model_name": model_name or "",
            "operation": operation or "",
            "success": bool(success),
            "latency_ms": int(latency_ms or 0),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(total_tokens or 0),
            "input_count": int(input_count or 0),
            "error_type": _clip(error_type, 120),
            "error_message": _clip(error_message, 500),
            "created_at": datetime.now(),
        }
        return _public(_get_repo().add(row))
    except Exception as exc:  # noqa: BLE001
        logger.warning("模型用量记录失败，已忽略：%s", exc)
        return None


def _since(days: int) -> datetime:
    days = max(1, min(int(days or 1), 90))
    return datetime.now() - timedelta(days=days)


def list_records(
    days: int = 7,
    user_id: int | None = None,
    model_type: str | None = None,
    success: bool | None = None,
    limit: int = 100,
) -> list[dict]:
    rows = _get_repo().list_records(_since(days), user_id, model_type, success, max(1, min(limit, 500)))
    return [_public(r) for r in rows]


def _metric(rows: list[dict]) -> dict:
    total = len(rows)
    success_count = sum(1 for r in rows if bool(r.get("success")))
    failed = total - success_count
    latencies = [int(r.get("latency_ms") or 0) for r in rows]
    latencies_sorted = sorted(latencies)
    if latencies_sorted:
        p95_index = min(len(latencies_sorted) - 1, int(len(latencies_sorted) * 0.95))
        p95 = latencies_sorted[p95_index]
    else:
        p95 = 0
    return {
        "call_count": total,
        "success_count": success_count,
        "failed_count": failed,
        "success_rate": round(success_count / total, 4) if total else 0.0,
        "error_rate": round(failed / total, 4) if total else 0.0,
        "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
        "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in rows),
        "total_tokens": sum(int(r.get("total_tokens") or 0) for r in rows),
        "avg_latency_ms": round(sum(latencies) / total, 1) if total else 0.0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "p95_latency_ms": p95,
    }


def _group(rows: list[dict], key: str) -> list[dict]:
    buckets: dict = {}
    for row in rows:
        value = row.get(key)
        buckets.setdefault(value, []).append(row)
    out = []
    for value, bucket in buckets.items():
        item = _metric(bucket)
        item[key] = value
        out.append(item)
    out.sort(key=lambda x: (x.get("total_tokens", 0), x.get("call_count", 0)), reverse=True)
    return out


def _daily(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        day = _to_datetime(row.get("created_at")).strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(row)
    out = []
    for day in sorted(buckets):
        item = _metric(buckets[day])
        item["date"] = day
        out.append(item)
    return out


def summarize(days: int = 7, user_id: int | None = None, model_type: str | None = None) -> dict:
    rows = _get_repo().list_records(_since(days), user_id, model_type, None, None)
    public_rows = [_public(r) for r in rows]
    return {
        "days": max(1, min(int(days or 1), 90)),
        "overall": _metric(public_rows),
        "by_model_type": _group(public_rows, "model_type"),
        "by_user": _group(public_rows, "user_id"),
        "daily_trend": _daily(public_rows),
    }


def _latency_threshold(model_type: str) -> int:
    if model_type == MODEL_EMBEDDING:
        return MODEL_USAGE_ALERT_LATENCY_EMBEDDING_MS
    if model_type == MODEL_RERANK:
        return MODEL_USAGE_ALERT_LATENCY_RERANK_MS
    return MODEL_USAGE_ALERT_LATENCY_CHAT_MS


def list_alerts(days: int = 1) -> list[dict]:
    rows = [_public(r) for r in _get_repo().list_records(_since(days), None, None, None, None)]
    alerts = []

    for item in _group(rows, "model_type"):
        call_count = item["call_count"]
        if call_count < MODEL_USAGE_ALERT_MIN_CALLS:
            continue
        model_type = item.get("model_type") or "unknown"
        error_rate = item.get("error_rate", 0.0)
        if error_rate >= MODEL_USAGE_ALERT_ERROR_RATE:
            alerts.append(
                {
                    "type": "error_rate_high",
                    "severity": "error",
                    "model_type": model_type,
                    "user_id": None,
                    "title": "模型调用失败率过高",
                    "message": f"{model_type} 最近 {days} 天失败率 {round(error_rate * 100, 1)}%，请检查供应商/API Key/网络。",
                    "current_value": error_rate,
                    "threshold": MODEL_USAGE_ALERT_ERROR_RATE,
                }
            )
        latency_threshold = _latency_threshold(model_type)
        if item.get("avg_latency_ms", 0) >= latency_threshold:
            alerts.append(
                {
                    "type": "latency_high",
                    "severity": "warning",
                    "model_type": model_type,
                    "user_id": None,
                    "title": "模型平均响应延迟过高",
                    "message": f"{model_type} 最近 {days} 天平均延迟 {item['avg_latency_ms']}ms，超过阈值 {latency_threshold}ms。",
                    "current_value": item.get("avg_latency_ms", 0),
                    "threshold": latency_threshold,
                }
            )

    for item in _group(rows, "user_id"):
        user_id = item.get("user_id")
        total_tokens = item.get("total_tokens", 0)
        if user_id is not None and total_tokens >= MODEL_USAGE_ALERT_TOKEN_DAILY:
            alerts.append(
                {
                    "type": "token_spike",
                    "severity": "warning",
                    "model_type": None,
                    "user_id": user_id,
                    "title": "用户 token 消耗较高",
                    "message": f"用户 #{user_id} 最近 {days} 天消耗 {total_tokens} tokens，超过阈值 {MODEL_USAGE_ALERT_TOKEN_DAILY}。",
                    "current_value": total_tokens,
                    "threshold": MODEL_USAGE_ALERT_TOKEN_DAILY,
                }
            )
    return alerts


# ---- 测试辅助 ----
def _set_repo_for_test(repo) -> None:
    global _repo
    _repo = repo


def _reset_repo_for_test() -> None:
    global _repo
    _repo = None

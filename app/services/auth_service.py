"""JWT 认证服务：签发与校验登录令牌。

令牌载荷（payload）：
    sub  : 用户名（subject）
    uid  : 用户 id
    role : 角色（admin / user）
    exp  : 过期时间（由 PyJWT 校验）

只负责 token 的编解码，不碰数据库；账号校验在 user_service。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET


class TokenError(Exception):
    """令牌无效或过期。上层据此返回 401。"""


def create_access_token(user: dict) -> str:
    """根据用户公开视图签发 JWT。user 需含 username / id / role。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["username"],
        "uid": user["id"],
        "role": user.get("role", "user"),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """校验并解出 payload；无效或过期抛 TokenError。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("登录凭证无效") from exc

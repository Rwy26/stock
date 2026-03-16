from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from passlib.hash import pbkdf2_sha256


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or password_hash.strip() in {"!", "*"}:
        return False
    try:
        return pbkdf2_sha256.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(*, subject: str, secret: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def decode_access_token_allow_expired(
    token: str,
    *,
    secret: str,
    max_expired_seconds: int,
) -> dict[str, Any]:
    """Decode token even if expired, but only within a short grace window.

    Used for access-token refresh to avoid hard logouts due to small clock drift.
    """

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False})
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")

        exp = payload.get("exp")
        if exp is None:
            raise ValueError("missing exp")
        exp_ts = int(exp)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if now_ts - exp_ts > int(max_expired_seconds):
            raise HTTPException(status_code=401, detail="Token expired")

        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def require_bearer(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return credentials.credentials

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    salt = hashlib.sha256(get_settings().app_secret_key.encode()).digest()
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000).hex()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def create_access_token(subject: str, role: str, organization_id: str | None = None, warehouse_ids: list[str] | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": subject, "role": role, "iat": now, "exp": now + timedelta(hours=8)}
    if organization_id is not None:
        claims["organization_id"] = organization_id
    if warehouse_ids is not None:
        claims["warehouse_ids"] = warehouse_ids
    return jwt.encode(claims, get_settings().app_secret_key, algorithm="HS256")


def verify_open_signature(app_key: str, timestamp: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    raw = f"{app_key}:{timestamp}:{get_settings().open_api_app_secret}".encode()
    expected = hashlib.sha256(raw).hexdigest()
    return hmac.compare_digest(expected, signature)

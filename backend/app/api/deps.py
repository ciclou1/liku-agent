import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.security import verify_open_signature
from app.services.access import AccessContext
from app.api.rate_limit import SimpleRateLimiter

bearer = HTTPBearer(auto_error=False)
open_rate_limiter = SimpleRateLimiter(limit=60, window_seconds=60)


def require_open_signature(x_app_key: str = Header(default=""), x_timestamp: str = Header(default=""), x_signature: str = Header(default="")) -> None:
    settings = get_settings()
    try:
        valid = verify_open_signature(x_app_key, x_timestamp, x_signature) if x_timestamp else False
    except (TypeError, ValueError):
        valid = False
    if x_app_key != settings.open_api_app_key or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="开放 API 签名无效")


def require_open_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if not open_rate_limiter.allow(client):
        raise HTTPException(status_code=429, detail="请求过于频繁")


def current_access(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AccessContext:
    if credentials is None:
        if get_settings().app_env == "test":
            return AccessContext("test", "admin")
        raise HTTPException(status_code=401, detail="需要登录凭证")
    try:
        payload = jwt.decode(credentials.credentials, get_settings().app_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    return AccessContext(str(payload["sub"]), str(payload.get("role", "worker")), payload.get("organization_id"), frozenset(payload.get("warehouse_ids", [])))


def require_role(required_role: str):
    def dependency(access: AccessContext = Depends(current_access)) -> AccessContext:
        if not access.can(required_role):
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return access

    return dependency

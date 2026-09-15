"""ERP 分析接口访问令牌：时效短、绑定申请行（prnum/prlinenum/itemnum）的 HMAC 签名 token。

格式：v1.{expiry}.{prnum or '-'}.{itemnum or '-'}.{linenum or '-'}.{hmac}
签名：HMAC-SHA256(app_secret, "{prnum}|{itemnum}|{linenum}|{expiry}")

场景：积木 ERP 嵌入页无法直接携带平台 JWT，落地页先以申请行参数换取
短期（默认 30 分钟）token，后续请求通过 X-ERP-Token 头携带；token 只能
访问其绑定的申请行（含行号）、物资。平台 JWT 登录用户走 Authorization 头，
不受绑定限制。

公开换 token 的端点受 erp_public_read 开关（默认关闭）与限流控制，
生产应接 ERP SSO 或由服务端签发。
"""
from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import get_settings

TOKEN_TTL_SECONDS = 30 * 60
_PREFIX = "v1"
_EMPTY = "-"


class ErpTokenError(Exception):
    pass


def _sign(prnum: str, itemnum: str, linenum: str, expiry: int) -> str:
    secret = get_settings().app_secret_key
    payload = f"{prnum}|{itemnum}|{linenum}|{expiry}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_read_token(prnum: str | None = None, itemnum: str | None = None,
                      prlinenum: int | str | None = None,
                      ttl_seconds: int = TOKEN_TTL_SECONDS) -> tuple[str, int]:
    """返回 (token, expires_in)。不传绑定值 = 仅检索类 token。"""
    p, i, ln = str(prnum or _EMPTY), str(itemnum or _EMPTY), str(prlinenum or _EMPTY)
    expiry = int(time.time()) + ttl_seconds
    token = f"{_PREFIX}.{expiry}.{p}.{i}.{ln}.{_sign(p, i, ln, expiry)}"
    return token, ttl_seconds


def verify_read_token(token: str, prnum: str | None = None, itemnum: str | None = None,
                      prlinenum: int | str | None = None) -> None:
    """校验签名、有效期与绑定范围：请求的申请行（含行号）必须落在 token 绑定范围内。

    - 绑定 '-' 的维度不可用于该维度的具体查询（检索类 token）
    - 绑定了具体值的维度，请求值必须与之相等（token 绑定行号时请求不得换行）
    - token 未绑定行号而请求带行号 → 视为在绑定申请内换行，拒绝（防横向查看）
    """
    try:
        prefix, expiry_raw, token_p, token_i, token_ln, sig = token.split(".")
        expiry = int(expiry_raw)
    except (ValueError, AttributeError) as exc:
        raise ErpTokenError("token 格式无效") from exc
    if prefix != _PREFIX or not hmac.compare_digest(sig, _sign(token_p, token_i, token_ln, expiry)):
        raise ErpTokenError("token 签名无效")
    if expiry < int(time.time()):
        raise ErpTokenError("token 已过期")
    req_p = str(prnum or _EMPTY)
    req_i = str(itemnum or _EMPTY)
    req_ln = str(prlinenum or _EMPTY)
    if (token_p != _EMPTY and req_p != token_p) or (token_i != _EMPTY and req_i != token_i):
        raise ErpTokenError("token 与请求的申请行不匹配")
    # 行号绑定规则：token 绑定了行号 → 请求必须同号；token 未绑定行号 → 请求也不得指定
    if token_ln != _EMPTY and req_ln != token_ln:
        raise ErpTokenError("token 与请求的申请行号不匹配")
    if token_ln == _EMPTY and req_ln not in (_EMPTY, "None"):
        raise ErpTokenError("token 未绑定申请行号")
    if token_p == _EMPTY and token_i == _EMPTY and (prnum or itemnum or prlinenum):
        # 检索类 token 不能访问具体分析（需带申请行绑定）
        raise ErpTokenError("token 未绑定申请行，无法访问分析数据")

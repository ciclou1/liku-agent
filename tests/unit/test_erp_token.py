"""ERP 只读 token：签发/校验/过期/绑定范围"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.erp.token import ErpTokenError, create_read_token, verify_read_token


def test_roundtrip_with_binding():
    token, ttl = create_read_token(prnum="PR252159", itemnum="20002183", prlinenum=5, ttl_seconds=60)
    assert ttl == 60
    verify_read_token(token, prnum="PR252159", itemnum="20002183", prlinenum=5)


def test_binding_scope_enforced():
    token, _ = create_read_token(prnum="PR252159", itemnum="20002183")
    with pytest.raises(ErpTokenError):
        verify_read_token(token, prnum="PR999999", itemnum="20002183")
    with pytest.raises(ErpTokenError):
        verify_read_token(token, prnum="PR252159", itemnum="20006786")


def test_linenumber_binding_enforced():
    """行号纳入绑定：同申请同物资多行时不得换行查看"""
    token_ln5, _ = create_read_token(prnum="PR1", itemnum="I", prlinenum=5)
    verify_read_token(token_ln5, prnum="PR1", itemnum="I", prlinenum=5)
    with pytest.raises(ErpTokenError):
        verify_read_token(token_ln5, prnum="PR1", itemnum="I", prlinenum=6)
    # token 未绑定行号 → 请求也不得指定（防升级）
    token_no_ln, _ = create_read_token(prnum="PR1", itemnum="I")
    verify_read_token(token_no_ln, prnum="PR1", itemnum="I")
    with pytest.raises(ErpTokenError):
        verify_read_token(token_no_ln, prnum="PR1", itemnum="I", prlinenum=5)


def test_search_token_cannot_access_analysis():
    token, _ = create_read_token()
    # 检索类 token（未绑定）可作检索
    verify_read_token(token)
    # 但不能访问具体分析
    with pytest.raises(ErpTokenError):
        verify_read_token(token, prnum="PR252159", itemnum="20002183")


def test_expired_token_rejected():
    token, _ = create_read_token(prnum="P", itemnum="I", ttl_seconds=-1)
    with pytest.raises(ErpTokenError):
        verify_read_token(token, prnum="P", itemnum="I")


def test_tampered_token_rejected():
    token, _ = create_read_token(prnum="P", itemnum="I")
    bad = token[:-4] + "0000"
    with pytest.raises(ErpTokenError):
        verify_read_token(bad, prnum="P", itemnum="I")

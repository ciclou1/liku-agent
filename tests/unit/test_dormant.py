"""呆滞处置建议算法（纯函数）测试"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.algorithms.dormant import RETURN, SCRAP, TRANSFER, classify_disposal

TODAY = date(2026, 9, 17)


def _row(**overrides):
    row = {
        "sku": "20002183", "warehouse_id": "P",
        "available_quantity": 10, "unit_cost": 25.0,
        "last_used_at": date(2024, 1, 1),
    }
    row.update(overrides)
    return row


def test_transfer_priority_over_return_and_scrap():
    result = classify_disposal(_row(has_transfer_demand=True, demand_warehouse="生产物资仓库",
                                    last_purchase={"date": "2026-05-01", "supplier": "甲公司"}), TODAY)
    assert result.suggestion == TRANSFER
    assert "现存量低于需求" in result.basis
    assert result.amount == 250.0


def test_return_when_recent_purchase():
    result = classify_disposal(_row(last_purchase={"date": "2026-05-01", "supplier": "甲公司"}), TODAY)
    assert result.suggestion == RETURN
    assert "甲公司" in result.basis


def test_scrap_when_no_signals():
    result = classify_disposal(_row(last_used_at=date(2024, 1, 1)), TODAY)
    assert result.suggestion == SCRAP
    assert result.days_idle is not None and result.days_idle >= 730
    assert "报废" in result.basis


def test_scrap_never_used():
    result = classify_disposal(_row(last_used_at=None), TODAY)
    assert result.suggestion == SCRAP
    assert result.days_idle is None
    assert "从未" in result.basis


def test_transfer_signal_in_other_warehouse_only_counts():
    # 缺口仓与呆滞仓相同时，调用方应已过滤掉（传入 has_transfer_demand=False）
    result = classify_disposal(_row(has_transfer_demand=False), TODAY)
    assert result.suggestion in {RETURN, SCRAP}


def test_amount_calculation():
    result = classify_disposal(_row(available_quantity=3, unit_cost=0.5), TODAY)
    assert result.amount == 1.5

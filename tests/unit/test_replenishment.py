"""安全库存优化算法（纯函数）测试"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.algorithms.replenishment import optimize_replenishment


def test_rop_math_with_known_series():
    # 12 个月稳定消耗 = 100/月 → μ=100，σ=0；L=2 → 安全库存=0，ROP=200
    result = optimize_replenishment(monthly_usage=[100.0] * 12, lead_time_months=2,
                                    current_safety=0, available=50, in_transit=0)
    assert result is not None
    assert result.mu_monthly == 100.0
    assert result.sigma_monthly == 0.0
    assert result.suggested_safety == 0.0
    assert result.reorder_point == 200.0
    # 补货量 = ceil((100×3 − 50 − 0)/1) = 250
    assert result.reorder_quantity == 250.0


def test_safety_stock_increases_with_variability():
    variable = optimize_replenishment(monthly_usage=[0, 200] * 6, lead_time_months=2,
                                      current_safety=0, available=0, in_transit=0)
    stable = optimize_replenishment(monthly_usage=[100.0] * 12, lead_time_months=2,
                                    current_safety=0, available=0, in_transit=0)
    assert variable is not None and stable is not None
    assert variable.suggested_safety > stable.suggested_safety
    assert variable.reorder_point > stable.reorder_point


def test_insufficient_data_returns_none():
    assert optimize_replenishment(monthly_usage=[10.0, 20.0], lead_time_months=1,
                                  current_safety=0, available=0, in_transit=0) is None


def test_package_size_rounding():
    result = optimize_replenishment(monthly_usage=[10.0] * 12, lead_time_months=1,
                                    current_safety=0, available=5, in_transit=0,
                                    package_size=24)
    # 需求 30 − 5 = 25 → ceil(25/24)=2 箱 → 48
    assert result is not None and result.reorder_quantity == 48.0


def test_in_transit_and_available_reduce_reorder():
    without = optimize_replenishment(monthly_usage=[50.0] * 6, lead_time_months=1,
                                     current_safety=0, available=0, in_transit=0)
    with_stock = optimize_replenishment(monthly_usage=[50.0] * 6, lead_time_months=1,
                                        current_safety=0, available=200, in_transit=100)
    assert without is not None and with_stock is not None
    assert without.reorder_quantity == 150.0
    assert with_stock.reorder_quantity == 0.0


def test_safety_gap_sign():
    below = optimize_replenishment(monthly_usage=[100.0] * 12, lead_time_months=4,
                                   current_safety=0, available=0, in_transit=0)
    above = optimize_replenishment(monthly_usage=[0.0] * 12, lead_time_months=1,
                                   current_safety=100, available=0, in_transit=0)
    assert below is not None and below.safety_gap >= 0
    assert above is not None and above.safety_gap <= 0


def test_invalid_lead_time_floors_to_one_month():
    result = optimize_replenishment(monthly_usage=[100.0] * 12, lead_time_months=0,
                                    current_safety=0, available=0, in_transit=0)
    assert result is not None and result.lead_time_months == 1.0


def test_formula_explanation_present():
    result = optimize_replenishment(monthly_usage=[10.0] * 12, lead_time_months=1,
                                    current_safety=0, available=0, in_transit=0)
    assert result is not None
    assert {"safety", "reorder_point", "reorder_quantity"} <= set(result.formula_explanation)


@pytest.mark.parametrize("usage,lead", [([5.0, 5.0, 5.0], 1), ([0, 0, 0, 0], 2)])
def test_minimum_series_accepted(usage, lead):
    assert optimize_replenishment(usage, lead, 0, 0, 0) is not None

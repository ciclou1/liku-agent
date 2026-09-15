from datetime import date, timedelta

import pytest

from app.algorithms.demand import ConsumptionPattern, classify_consumption, forecast_demand, sba
from app.algorithms.liku import PurchaseInput, WarehouseStock, calculate_purchase_recommendation, match_transfers
from app.algorithms.metrics import directional_accuracy, mape, wape
from app.algorithms.price import TimingSignal, forecast_price
from app.algorithms.warning import WarningLevel, WarningType, detect_warnings


def test_metrics_are_deterministic() -> None:
    assert wape([10, 20], [8, 25]) == pytest.approx(7 / 30)
    assert mape([10, 20], [8, 25]) == pytest.approx(0.225)
    assert directional_accuracy([10, 12, 9], [10, 11, 8]) == pytest.approx(1.0)


def test_consumption_classification_and_interval() -> None:
    assert classify_consumption([10, 11, 9, 10]) is ConsumptionPattern.STABLE
    assert classify_consumption([0, 0, 10, 0, 4]) is ConsumptionPattern.SPARE_PART
    pattern, forecast = forecast_demand([10, 12, 11, 9], horizon=3)
    assert pattern == "stable"
    assert len(forecast) == 3
    assert forecast[0].lower <= forecast[0].value <= forecast[0].upper
    assert sba([0, 0, 10]) > 0


def test_purchase_quantity_rounds_to_package_and_handles_stock() -> None:
    item = PurchaseInput("A", "电缆", 80, 20, 30, 10, 24)
    recommendation = calculate_purchase_recommendation(item)
    assert recommendation.net_gap == 60
    assert recommendation.purchase_quantity == 72
    assert recommendation.calculation_basis["rounded_quantity"] == 72


def test_zero_package_is_rejected() -> None:
    with pytest.raises(ValueError, match="package_size"):
        calculate_purchase_recommendation(PurchaseInput("A", "", 1, 1, 0, 0, 0))


def test_transfer_matching_prefers_nearby_donor() -> None:
    stocks = [
        WarehouseStock("A", "source-far", "org", 100, 20, 2),
        WarehouseStock("A", "source-near", "org", 70, 20, 2),
        WarehouseStock("A", "target", "org", 0, 80, 2),
    ]
    transfers = match_transfers(stocks, {("source-near", "target"): (5, 1), ("source-far", "target"): (50, 3)})
    assert transfers[0].source_warehouse_id == "source-near"
    assert sum(item.quantity for item in transfers) == pytest.approx(80)


def test_price_forecast_generates_timing_signal() -> None:
    forecast = forecast_price("A", [10, 11, 12, 14], demand_urgency=0.2)
    assert forecast.direction == "up"
    assert forecast.signal is TimingSignal.STOCK_UP
    assert forecast.expected_saving >= 0


def test_price_saving_uses_current_price_and_purchase_quantity() -> None:
    result = forecast_price("A", [10, 10.5, 11, 11.5, 12, 12.5], purchase_quantity=4, demand_urgency=0.5)
    assert result.signal is TimingSignal.STOCK_UP
    assert result.expected_saving == pytest.approx((max(result.prices) - 12.5) * 4)
    assert forecast_price("A", [10, 10.5, 11, 11.5, 12, 12.5], purchase_quantity=0).expected_saving == 0


def test_warning_detection_and_actions() -> None:
    today = date(2026, 9, 8)
    item = {
        "sku": "A",
        "warehouse_id": "W1",
        "last_used_at": today - timedelta(days=800),
        "expiry_date": today + timedelta(days=20),
        "available_quantity": 10,
        "safety_stock": 2,
        "unit_cost": 3,
    }
    warnings = detect_warnings(item, today)
    assert {warning.warning_type for warning in warnings} == {WarningType.STAGNANT, WarningType.OVERSTOCK, WarningType.EXPIRING}
    assert any(warning.level is WarningLevel.CRITICAL for warning in warnings)
    assert all(warning.action for warning in warnings)

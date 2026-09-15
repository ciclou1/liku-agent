from dataclasses import dataclass, asdict
from math import ceil
from typing import Iterable


@dataclass(frozen=True)
class PurchaseInput:
    sku: str
    category: str
    forecast_demand: float
    safety_stock: float
    available_stock: float
    in_transit: float
    package_size: float


@dataclass(frozen=True)
class PurchaseRecommendation:
    sku: str
    category: str
    purchase_quantity: float
    net_gap: float
    calculation_basis: dict[str, float | str]
    timing_signal: str = "normal"
    reference_price_low: float | None = None
    reference_price_high: float | None = None
    expected_saving: float = 0.0


@dataclass(frozen=True)
class WarehouseStock:
    sku: str
    warehouse_id: str
    organization_id: str
    available_quantity: float
    safety_stock: float
    unit_cost: float


@dataclass(frozen=True)
class TransferRecommendation:
    sku: str
    source_warehouse_id: str
    target_warehouse_id: str
    quantity: float
    distance_km: float
    lead_time_days: int


def calculate_purchase_recommendation(item: PurchaseInput, timing_signal: str = "normal", saving: float = 0.0, reference_price_low: float | None = None, reference_price_high: float | None = None) -> PurchaseRecommendation:
    if item.package_size <= 0:
        raise ValueError("package_size must be greater than zero")
    net_gap = max(0.0, item.forecast_demand + item.safety_stock - item.available_stock - item.in_transit)
    quantity = ceil(net_gap / item.package_size) * item.package_size
    basis = {**asdict(item), "net_gap": net_gap, "rounded_quantity": quantity}
    return PurchaseRecommendation(item.sku, item.category, quantity, net_gap, basis, timing_signal, reference_price_low, reference_price_high, saving)


def match_transfers(stocks: Iterable[WarehouseStock], distances: dict[tuple[str, str], tuple[float, int]]) -> list[TransferRecommendation]:
    grouped: dict[str, list[WarehouseStock]] = {}
    for stock in stocks:
        grouped.setdefault(stock.sku, []).append(stock)
    recommendations: list[TransferRecommendation] = []
    for sku, items in grouped.items():
        donors = [item for item in items if item.available_quantity > item.safety_stock]
        receivers = [item for item in items if item.available_quantity < item.safety_stock]
        for receiver in sorted(receivers, key=lambda item: item.available_quantity):
            for donor in sorted(donors, key=lambda item: distances.get((item.warehouse_id, receiver.warehouse_id), (float("inf"), 999))[0]):
                if donor.available_quantity <= donor.safety_stock:
                    continue
                quantity = min(donor.available_quantity - donor.safety_stock, receiver.safety_stock - receiver.available_quantity)
                if quantity <= 0:
                    continue
                distance, lead_time = distances.get((donor.warehouse_id, receiver.warehouse_id), (0.0, 0))
                recommendations.append(TransferRecommendation(sku, donor.warehouse_id, receiver.warehouse_id, quantity, distance, lead_time))
                donors[donors.index(donor)] = WarehouseStock(donor.sku, donor.warehouse_id, donor.organization_id, donor.available_quantity - quantity, donor.safety_stock, donor.unit_cost)
                receiver = WarehouseStock(receiver.sku, receiver.warehouse_id, receiver.organization_id, receiver.available_quantity + quantity, receiver.safety_stock, receiver.unit_cost)
                if receiver.available_quantity >= receiver.safety_stock:
                    break
    return recommendations

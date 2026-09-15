from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class InventoryItem(BaseModel):
    sku: str
    name: str
    warehouse_id: str
    warehouse_name: str
    available_quantity: float
    in_transit: float
    unit_cost: float
    safety_stock: float
    last_used_at: date | None = None
    expiry_date: date | None = None


class ForecastResponse(BaseModel):
    sku: str
    warehouse_id: str
    pattern: str
    history: list[dict[str, Any]]
    forecast: list[dict[str, Any]]
    corrected: bool = False
    model_name: str = "baseline"
    backtest: dict[str, float | int | str] = Field(default_factory=dict)
    narrative: str = ""


class ForecastCorrection(BaseModel):
    values: list[float] = Field(min_length=1)


class PurchaseRequest(BaseModel):
    sku: str
    category: str = "未分类"
    forecast_demand: float = Field(ge=0)
    safety_stock: float = Field(ge=0)
    available_stock: float
    in_transit: float = Field(default=0, ge=0)
    package_size: float = Field(gt=0)
    timing_signal: str = "normal"
    expected_saving: float = Field(default=0, ge=0)
    warehouse_id: str = Field(default="W1", min_length=1, max_length=80)


class PlanningRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    warehouse_id: str = Field(default="W1", min_length=1, max_length=80)


class TransferPlanningRequest(BaseModel):
    sku: str | None = Field(default=None, max_length=80)
    target_warehouse_id: str | None = Field(default=None, max_length=80)
    min_quantity: float = Field(default=0, ge=0)


class PurchaseResponse(BaseModel):
    sku: str
    category: str
    purchase_quantity: float
    net_gap: float
    timing_signal: str
    expected_saving: float
    reference_price_low: float | None = None
    reference_price_high: float | None = None
    calculation_basis: dict[str, Any]
    status: str = "generated"
    warehouse_id: str | None = None
    model_name: str | None = None
    forecast_demand: float | None = None
    data_source: str | None = None
    inventory_quantity: float | None = None
    reserved_quantity: float | None = None
    available_quantity: float | None = None
    summary: str | None = None
    calculation_explanation: dict[str, str] = Field(default_factory=dict)
    narrative: str = ""


class WarningResponse(BaseModel):
    sku: str
    warehouse_id: str
    warning_type: str
    level: str
    message: str
    action: str
    amount: float


class PriceResponse(BaseModel):
    sku: str
    periods: list[str]
    prices: list[float]
    direction: str
    signal: str
    expected_saving: float
    history: list[dict[str, str | float]] = Field(default_factory=list)
    backtest: dict[str, str | float | int] = Field(default_factory=dict)
    narrative: str = ""
    model_name: str = ""


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[str]
    tool_name: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str

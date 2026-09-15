from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Material(Base, TimestampMixin):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80), default="未分类")
    unit: Mapped[str] = mapped_column(String(20), default="件")
    package_size: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=1)
    shelf_life_days: Mapped[int | None] = mapped_column(nullable=True)


class ProcurementOrder(Base, TimestampMixin):
    __tablename__ = "procurement_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    supplier: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    ordered_at: Mapped[date] = mapped_column(Date)


class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    used_at: Mapped[date] = mapped_column(Date)
    work_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class InventorySnapshot(Base, TimestampMixin):
    __tablename__ = "inventory_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    available_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    in_transit_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    # per-SKU 安全库存（ERP 主库存项目 MINLEVEL）；0 = 未设置，回退分类规则
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    last_used_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class PriceRecord(Base, TimestampMixin):
    __tablename__ = "price_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    supplier: Mapped[str] = mapped_column(String(160))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    recorded_at: Mapped[date] = mapped_column(Date, index=True)


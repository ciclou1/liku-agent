from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Warehouse(Base, TimestampMixin):
    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    warehouse_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    organization_id: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    supplier_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(default=7)


class StockMovement(Base, TimestampMixin):
    __tablename__ = "stock_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(20), default="件")
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    reference_no: Mapped[str | None] = mapped_column(String(120), nullable=True)


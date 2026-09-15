from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RecommendationStatus(str):
    GENERATED = "generated"
    REVIEWED = "reviewed"
    EXPORTED = "exported"
    PUSHED = "pushed"


class IntegrationJob(Base, TimestampMixin):
    __tablename__ = "integration_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    adapter_name: Mapped[str] = mapped_column(String(80), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="incremental")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    rows_processed: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ForecastRecord(Base, TimestampMixin):
    __tablename__ = "forecast_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    lower_bound: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    upper_bound: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    pattern: Mapped[str] = mapped_column(String(30))
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)


class SafetyStockRule(Base, TimestampMixin):
    __tablename__ = "safety_stock_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    service_level: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0.95)


class PurchaseRecommendationRecord(Base, TimestampMixin):
    __tablename__ = "purchase_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    category: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(20), default="generated")
    timing_signal: Mapped[str] = mapped_column(String(30), default="normal")
    expected_saving: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    calculation_basis: Mapped[dict] = mapped_column(JSON, default=dict)

    def transition(self, target: str) -> None:
        if self.status == "no_purchase":
            raise ValueError("无需采购的建议不能进入审核流程")
        allowed = {
            RecommendationStatus.GENERATED: {RecommendationStatus.REVIEWED},
            RecommendationStatus.REVIEWED: {RecommendationStatus.EXPORTED, RecommendationStatus.PUSHED},
            RecommendationStatus.EXPORTED: {RecommendationStatus.PUSHED},
            RecommendationStatus.PUSHED: set(),
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(f"invalid recommendation transition: {self.status} -> {target}")
        self.status = target


class TransferRoute(Base, TimestampMixin):
    __tablename__ = "transfer_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    target_warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    lead_time_days: Mapped[int] = mapped_column(default=0)
    organization_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class WarningRule(Base, TimestampMixin):
    __tablename__ = "warning_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    warning_type: Mapped[str] = mapped_column(String(30), index=True)
    level: Mapped[str] = mapped_column(String(20))
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(80), index=True)
    warning_type: Mapped[str] = mapped_column(String(30), index=True)
    level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    message: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)


class PriceTarget(Base, TimestampMixin):
    __tablename__ = "price_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource: Mapped[str] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="新会话")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)

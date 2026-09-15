"""create initial application tables"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("username", sa.String(80), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("role", sa.String(40), nullable=False), sa.Column("organization_id", sa.String(80)), sa.Column("warehouse_ids", sa.JSON), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table("tasks", sa.Column("id", sa.String(36), primary_key=True), sa.Column("task_type", sa.String(80), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("config", sa.JSON), sa.Column("result", sa.JSON), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_tasks_task_type", "tasks", ["task_type"])
    op.create_table("materials", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("category", sa.String(80), nullable=False), sa.Column("unit", sa.String(20), nullable=False), sa.Column("package_size", sa.Numeric(18, 4), nullable=False), sa.Column("shelf_life_days", sa.Integer), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_materials_sku", "materials", ["sku"], unique=True)
    for table, columns in {
        "procurement_orders": [("sku", sa.String(80)), ("warehouse_id", sa.String(80)), ("supplier", sa.String(160)), ("quantity", sa.Numeric(18, 4)), ("unit_price", sa.Numeric(18, 4)), ("ordered_at", sa.Date)],
        "usage_records": [("sku", sa.String(80)), ("warehouse_id", sa.String(80)), ("quantity", sa.Numeric(18, 4)), ("used_at", sa.Date), ("work_order_id", sa.String(80))],
        "inventory_snapshots": [("sku", sa.String(80)), ("warehouse_id", sa.String(80)), ("available_quantity", sa.Numeric(18, 4)), ("in_transit_quantity", sa.Numeric(18, 4)), ("unit_cost", sa.Numeric(18, 4)), ("last_used_at", sa.Date), ("expiry_date", sa.Date)],
        "price_records": [("sku", sa.String(80)), ("supplier", sa.String(160)), ("price", sa.Numeric(18, 4)), ("recorded_at", sa.Date)],
    }.items():
        op.create_table(table, sa.Column("id", sa.String(36), primary_key=True), *[sa.Column(name, column_type) for name, column_type in columns], sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("integration_jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("adapter_name", sa.String(80), nullable=False), sa.Column("mode", sa.String(20), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("rows_processed", sa.Integer, nullable=False), sa.Column("error_message", sa.Text), sa.Column("started_at", sa.DateTime), sa.Column("finished_at", sa.DateTime), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("forecast_records", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("warehouse_id", sa.String(80), nullable=False), sa.Column("period", sa.String(20), nullable=False), sa.Column("value", sa.Numeric(18, 4), nullable=False), sa.Column("lower_bound", sa.Numeric(18, 4), nullable=False), sa.Column("upper_bound", sa.Numeric(18, 4), nullable=False), sa.Column("pattern", sa.String(30), nullable=False), sa.Column("corrected", sa.Boolean, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("safety_stock_rules", sa.Column("id", sa.String(36), primary_key=True), sa.Column("category", sa.String(80), nullable=False), sa.Column("quantity", sa.Numeric(18, 4), nullable=False), sa.Column("service_level", sa.Numeric(8, 4), nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_safety_stock_rules_category", "safety_stock_rules", ["category"], unique=True)
    op.create_table("purchase_recommendations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("category", sa.String(80), nullable=False), sa.Column("quantity", sa.Numeric(18, 4), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("timing_signal", sa.String(30), nullable=False), sa.Column("expected_saving", sa.Numeric(18, 4), nullable=False), sa.Column("calculation_basis", sa.JSON), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("transfer_routes", sa.Column("id", sa.String(36), primary_key=True), sa.Column("source_warehouse_id", sa.String(80), nullable=False), sa.Column("target_warehouse_id", sa.String(80), nullable=False), sa.Column("distance_km", sa.Numeric(12, 3), nullable=False), sa.Column("lead_time_days", sa.Integer, nullable=False), sa.Column("organization_id", sa.String(80)), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("warning_rules", sa.Column("id", sa.String(36), primary_key=True), sa.Column("warning_type", sa.String(30), nullable=False), sa.Column("level", sa.String(20), nullable=False), sa.Column("threshold", sa.Numeric(18, 4), nullable=False), sa.Column("scope", sa.JSON), sa.Column("enabled", sa.Boolean, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("alerts", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("warehouse_id", sa.String(80), nullable=False), sa.Column("warning_type", sa.String(30), nullable=False), sa.Column("level", sa.String(20), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("message", sa.Text, nullable=False), sa.Column("action", sa.Text, nullable=False), sa.Column("amount", sa.Numeric(18, 4), nullable=False), sa.Column("dedupe_key", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_alerts_dedupe_key", "alerts", ["dedupe_key"], unique=True)
    op.create_table("price_targets", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("enabled", sa.Boolean, nullable=False), sa.Column("notes", sa.Text), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_price_targets_sku", "price_targets", ["sku"], unique=True)
    op.create_table("audit_logs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("actor", sa.String(80), nullable=False), sa.Column("action", sa.String(120), nullable=False), sa.Column("resource", sa.String(120), nullable=False), sa.Column("detail", sa.JSON), sa.Column("created_at", sa.DateTime, nullable=False))
    op.create_table("chat_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(80)), sa.Column("title", sa.String(160), nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_table("chat_messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text, nullable=False), sa.Column("sources", sa.JSON), sa.Column("created_at", sa.DateTime, nullable=False))


def downgrade() -> None:
    for table in ("chat_messages", "chat_sessions", "audit_logs", "price_targets", "alerts", "warning_rules", "transfer_routes", "purchase_recommendations", "safety_stock_rules", "forecast_records", "integration_jobs", "price_records", "inventory_snapshots", "usage_records", "procurement_orders", "materials", "tasks", "users"):
        op.drop_table(table)

"""add warehouse supplier and stock movement tables"""
from alembic import op
import sqlalchemy as sa

revision = "0002_demo_master_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("warehouses", sa.Column("id", sa.String(36), primary_key=True), sa.Column("warehouse_id", sa.String(80), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("organization_id", sa.String(80), nullable=False), sa.Column("city", sa.String(80)), sa.Column("latitude", sa.Numeric(10, 7)), sa.Column("longitude", sa.Numeric(10, 7)), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_warehouses_warehouse_id", "warehouses", ["warehouse_id"], unique=True)
    op.create_index("ix_warehouses_organization_id", "warehouses", ["organization_id"])
    op.create_table("suppliers", sa.Column("id", sa.String(36), primary_key=True), sa.Column("supplier_code", sa.String(80), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("contact_name", sa.String(80)), sa.Column("lead_time_days", sa.Integer, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_suppliers_supplier_code", "suppliers", ["supplier_code"], unique=True)
    op.create_table("stock_movements", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sku", sa.String(80), nullable=False), sa.Column("warehouse_id", sa.String(80), nullable=False), sa.Column("movement_type", sa.String(30), nullable=False), sa.Column("quantity", sa.Numeric(18, 4), nullable=False), sa.Column("unit", sa.String(20), nullable=False), sa.Column("posting_date", sa.Date, nullable=False), sa.Column("reference_no", sa.String(120)), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    op.create_index("ix_stock_movements_sku", "stock_movements", ["sku"])
    op.create_index("ix_stock_movements_warehouse_id", "stock_movements", ["warehouse_id"])
    op.create_index("ix_stock_movements_movement_type", "stock_movements", ["movement_type"])
    op.create_index("ix_stock_movements_posting_date", "stock_movements", ["posting_date"])


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_table("suppliers")
    op.drop_table("warehouses")


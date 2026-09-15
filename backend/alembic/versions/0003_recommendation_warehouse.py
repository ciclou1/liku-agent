"""persist purchase recommendation warehouse scope"""
from alembic import op
import sqlalchemy as sa

revision = "0003_recommendation_warehouse"
down_revision = "0002_demo_master_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_recommendations", sa.Column("warehouse_id", sa.String(80), nullable=True))
    op.create_index("ix_purchase_recommendations_warehouse_id", "purchase_recommendations", ["warehouse_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_recommendations_warehouse_id", table_name="purchase_recommendations")
    op.drop_column("purchase_recommendations", "warehouse_id")

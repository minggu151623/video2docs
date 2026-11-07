"""Store where a generation's verification report lives."""

from alembic import op
from sqlalchemy import Column, String, inspect

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    existing = {col["name"] for col in inspect(op.get_bind()).get_columns("generations")}
    if "verification_json_path" not in existing:
        op.add_column("generations", Column("verification_json_path", String))


def downgrade():
    op.drop_column("generations", "verification_json_path")

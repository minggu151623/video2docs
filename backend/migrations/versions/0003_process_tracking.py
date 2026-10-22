"""Track owned media processes for crash recovery."""

from alembic import op
from sqlalchemy import Column, Integer, String, inspect

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    existing = {col["name"] for col in inspect(op.get_bind()).get_columns("jobs")}
    for column in (Column("subprocess_pid", Integer), Column("subprocess_signature", String)):
        if column.name not in existing:
            op.add_column("jobs", column)


def downgrade():
    op.drop_column("jobs", "subprocess_signature")
    op.drop_column("jobs", "subprocess_pid")

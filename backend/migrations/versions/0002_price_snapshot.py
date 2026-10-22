"""Dated Standard-tier public price reference, not an account billing guarantee."""

from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        text("""INSERT INTO price_snapshots
        (id,model,tier,effective_from,effective_to,input_rate,output_rate,currency,source_url,checked_at)
        VALUES (:id,:model,:tier,:start,:end,:input,:output,:currency,:url,:checked)"""),
        {
            "id": "20261020-gemini38-standard",
            "model": "gemini-3.8-flash",
            "tier": "standard",
            "start": "2026-10-20",
            "end": "2026-12-31",
            "input": 0.75,
            "output": 3.75,
            "currency": "USD",
            "url": "https://ai.google.dev/gemini-api/docs/pricing",
            "checked": "2026-10-20T00:00:00+00:00",
        },
    )


def downgrade():
    op.get_bind().execute(text("DELETE FROM price_snapshots WHERE id='20261020-gemini38-standard'"))

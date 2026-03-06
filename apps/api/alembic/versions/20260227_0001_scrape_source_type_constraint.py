"""Add scrape_sources.source_type and enum check constraint.

Revision ID: 20260227_0001
Revises:
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260227_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scrape_sources"):
        return
    columns = {c["name"] for c in inspector.get_columns("scrape_sources")}

    if "source_type" not in columns:
        op.add_column(
            "scrape_sources",
            sa.Column(
                "source_type",
                sa.String(length=30),
                nullable=False,
                server_default="generic",
            ),
        )

    constraints = {c["name"] for c in inspector.get_check_constraints("scrape_sources") if c.get("name")}
    if "ck_scrape_sources_source_type" not in constraints:
        op.create_check_constraint(
            "ck_scrape_sources_source_type",
            "scrape_sources",
            "source_type IN ('generic', 'canvas')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scrape_sources"):
        return
    constraints = {c["name"] for c in inspector.get_check_constraints("scrape_sources") if c.get("name")}
    if "ck_scrape_sources_source_type" in constraints:
        op.drop_constraint("ck_scrape_sources_source_type", "scrape_sources", type_="check")

    columns = {c["name"] for c in inspector.get_columns("scrape_sources")}
    if "source_type" in columns:
        op.drop_column("scrape_sources", "source_type")

"""Merge Alembic heads after notifications and profile dismissal branches.

Revision ID: 20260305_0016_merge
Revises: 20260302_0011, 20260305_0015
Create Date: 2026-03-05
"""

from alembic import op


revision = "20260305_0016_merge"
down_revision = ("20260302_0011", "20260305_0015")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

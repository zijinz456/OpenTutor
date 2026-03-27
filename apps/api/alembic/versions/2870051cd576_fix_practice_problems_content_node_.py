"""fix_practice_problems_content_node_ondelete_set_null

Revision ID: 2870051cd576
Revises: b8dc85d1df33
Create Date: 2026-03-27 22:14:15.786414

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2870051cd576'  # pragma: allowlist secret
down_revision: Union[str, None] = 'b8dc85d1df33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

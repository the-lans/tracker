"""tasks.context_cleared_at: when the session context was last cleared

Revision ID: b4e7c1d9a352
Revises: a8d3f5c2e914
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b4e7c1d9a352'
down_revision: Union[str, Sequence[str], None] = 'a8d3f5c2e914'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS context_cleared_at TIMESTAMP WITH TIME ZONE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS context_cleared_at")

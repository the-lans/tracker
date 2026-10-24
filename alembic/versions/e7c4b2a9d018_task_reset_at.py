"""tasks.reset_at: when the task was last returned to new

Revision ID: e7c4b2a9d018
Revises: d6a2e9b4c731
Create Date: 2026-10-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7c4b2a9d018'
down_revision: Union[str, Sequence[str], None] = 'd6a2e9b4c731'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS reset_at")

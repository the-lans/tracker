"""task_repositories.rebase_requested_at: rebase onto the new base by the task worker

Revision ID: a8d3f5c2e914
Revises: f2a9c6e1b374
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8d3f5c2e914'
down_revision: Union[str, Sequence[str], None] = 'f2a9c6e1b374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE task_repositories "
        "ADD COLUMN IF NOT EXISTS rebase_requested_at TIMESTAMP WITH TIME ZONE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE task_repositories DROP COLUMN IF EXISTS rebase_requested_at")

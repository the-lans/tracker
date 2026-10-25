"""task_nodes.pause_after: pause the task after the node succeeds

Revision ID: c6d2e8f4a170
Revises: b4e7c1d9a352
Create Date: 2026-10-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c6d2e8f4a170'
down_revision: Union[str, Sequence[str], None] = 'b4e7c1d9a352'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE task_nodes ADD COLUMN IF NOT EXISTS pause_after BOOLEAN NOT NULL DEFAULT false",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE task_nodes DROP COLUMN IF EXISTS pause_after")

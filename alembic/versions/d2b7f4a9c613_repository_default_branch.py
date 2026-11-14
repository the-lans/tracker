"""add repositories.default_branch

Revision ID: d2b7f4a9c613
Revises: c4e7a2b9d518
Create Date: 2026-11-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd2b7f4a9c613'
down_revision: Union[str, Sequence[str], None] = 'c4e7a2b9d518'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS default_branch VARCHAR NOT NULL DEFAULT 'master'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE repositories DROP COLUMN IF EXISTS default_branch")

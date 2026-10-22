"""add users.ssh_key_last_used_at for the SFTP gateway

Revision ID: a7c4e2f9b318
Revises: f3b8d1c6a920
Create Date: 2026-10-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7c4e2f9b318'
down_revision: Union[str, Sequence[str], None] = 'f3b8d1c6a920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ssh_key_last_used_at TIMESTAMP WITH TIME ZONE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS ssh_key_last_used_at")

"""node_logs.error_message: why the run failed

Revision ID: f4c2a8e6b913
Revises: e3b7c9d1f582
Create Date: 2026-10-28 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f4c2a8e6b913'
down_revision: Union[str, Sequence[str], None] = 'e3b7c9d1f582'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE node_logs ADD COLUMN IF NOT EXISTS error_message TEXT")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE node_logs DROP COLUMN IF EXISTS error_message")

"""node_logs.decision_output_offset: where in the answer the user decided

Revision ID: e3b7c9d1f582
Revises: d8a1f3b5c247
Create Date: 2026-10-28 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3b7c9d1f582'
down_revision: Union[str, Sequence[str], None] = 'd8a1f3b5c247'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE node_logs ADD COLUMN IF NOT EXISTS decision_output_offset INTEGER")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE node_logs DROP COLUMN IF EXISTS decision_output_offset")

"""add task_status 'paused'

Revision ID: b7d4e2a91c3f
Revises: 3c2aeeaf2142
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7d4e2a91c3f'
down_revision: Union[str, Sequence[str], None] = '3c2aeeaf2142'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'paused' AFTER 'in_progress'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL не умеет удалять значения enum-типа: значение 'paused'
    # остаётся в типе, задачи на паузе нужно вывести из неё до отката кода.
    pass

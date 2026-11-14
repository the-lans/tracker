"""Операции и пути в истории базы знаний."""

import sqlalchemy as sa
from alembic import op

revision = "28c0b4ef129a"
down_revision = "68b44af9f657"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_versions",
        sa.Column("operation", sa.String(32), nullable=False, server_default="save"),
    )
    op.add_column("knowledge_versions", sa.Column("path", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_versions", "path")
    op.drop_column("knowledge_versions", "operation")

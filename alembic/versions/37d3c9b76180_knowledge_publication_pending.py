"""Состояние синхронизации файлов базы знаний."""

import sqlalchemy as sa

from alembic import op

revision = "37d3c9b76180"
down_revision = "28c0b4ef129a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_sections",
        sa.Column(
            "publication_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_sections", "publication_pending")

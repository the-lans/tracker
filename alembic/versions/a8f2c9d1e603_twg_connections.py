"""Личные подключения TWG; добавление совместимо с предыдущим релизом."""

from alembic import op
import sqlalchemy as sa

revision = "a8f2c9d1e603"
down_revision = "e7b2d9c4a613"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "twg_connections",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("site", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("twg_connections")

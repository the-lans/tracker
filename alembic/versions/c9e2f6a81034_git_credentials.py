"""Учётные данные Git для новой установки; старое поле ключа удаляется."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9e2f6a81034"
down_revision: str | None = "a1d5f8c3e047"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "git_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
    )
    op.add_column(
        "repositories", sa.Column("git_credential_id", postgresql.UUID(as_uuid=True))
    )
    op.create_foreign_key(
        "fk_repository_git_credential",
        "repositories",
        "git_credentials",
        ["git_credential_id"],
        ["id"],
    )
    # По согласованным требованиям сохранение старых ключей не требуется.
    op.drop_column("repositories", "deploy_key_encrypted")


def downgrade() -> None:
    op.drop_constraint(
        "fk_repository_git_credential", "repositories", type_="foreignkey"
    )
    op.drop_column("repositories", "git_credential_id")
    op.add_column(
        "repositories",
        sa.Column(
            "deploy_key_encrypted",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("repositories", "deploy_key_encrypted", server_default=None)
    op.drop_table("git_credentials")

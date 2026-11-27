"""Отозвать прежние пользовательские токены при переходе на cookie."""

from alembic import op

revision = "f8c1a6d2b940"
down_revision = "e4ac0721df52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET session_version = session_version + 1")


def downgrade() -> None:
    # Отозванные токены не должны снова становиться действительными.
    pass

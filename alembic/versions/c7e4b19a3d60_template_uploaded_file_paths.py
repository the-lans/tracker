"""
Признак «файл загружен с диска» у файлов шаблона (раздел 3.1, 15.1).

Только добавление (раздел 20.6): прежняя версия столбец не читает.
"""

from alembic import op

revision = "c7e4b19a3d60"
down_revision = "a3f9d2c71e58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE templates ADD COLUMN IF NOT EXISTS "
        "uploaded_file_paths jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS uploaded_file_paths")

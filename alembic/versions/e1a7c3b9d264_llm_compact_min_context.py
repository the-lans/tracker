"""
Минимум контекста для сжатия при смене LLM-аккаунта в системных настройках
(раздел 19.7): короткий контекст не сжимается.

Только добавление (раздел 20.6): прежняя версия столбец не читает.
"""

from alembic import op

revision = "e1a7c3b9d264"
down_revision = "d9f4b7c2a158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS "
        "llm_compact_min_context_chars integer NOT NULL DEFAULT 12000",
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE system_settings ADD CONSTRAINT ck_system_settings_llm_compact_min_context_chars
                CHECK (llm_compact_min_context_chars BETWEEN 0 AND 10000000);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE system_settings DROP CONSTRAINT IF EXISTS "
        "ck_system_settings_llm_compact_min_context_chars",
    )
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS llm_compact_min_context_chars")

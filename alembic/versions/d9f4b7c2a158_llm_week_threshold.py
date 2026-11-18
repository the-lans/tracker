"""
Порог недельного расхода LLM-аккаунта в системных настройках (раздел 19.7):
при достижении задача уходит на другой аккаунт.

Только добавление (раздел 20.6): прежняя версия столбец не читает.
"""

from alembic import op

revision = "d9f4b7c2a158"
down_revision = "c8e2a6f4b139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS "
        "llm_switch_threshold_week_pct integer NOT NULL DEFAULT 98",
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE system_settings ADD CONSTRAINT ck_system_settings_llm_switch_threshold_week_pct
                CHECK (llm_switch_threshold_week_pct BETWEEN 1 AND 100);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE system_settings DROP CONSTRAINT IF EXISTS "
        "ck_system_settings_llm_switch_threshold_week_pct",
    )
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS llm_switch_threshold_week_pct")

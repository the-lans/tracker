"""add system_settings, task env key uniqueness, llm rate limit reset

Revision ID: d81e5b3c7a26
Revises: c4f1a8e2d905
Create Date: 2026-10-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd81e5b3c7a26'
down_revision: Union[str, Sequence[str], None] = 'c4f1a8e2d905'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Начальные значения — прежние константы кода (`NodeCreateRequest`,
    # `services/nodes/script.py::DEFAULT_RUNNER_IMAGES`).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            default_timeout_seconds INTEGER NOT NULL,
            default_max_retries INTEGER NOT NULL,
            default_retry_base_delay_seconds INTEGER NOT NULL,
            default_runner_image_python VARCHAR NOT NULL,
            default_runner_image_bash VARCHAR NOT NULL,
            CONSTRAINT ck_system_settings_single_row CHECK (id = 1)
        )
        """,
    )
    op.execute(
        """
        INSERT INTO system_settings (
            id, default_timeout_seconds, default_max_retries,
            default_retry_base_delay_seconds, default_runner_image_python,
            default_runner_image_bash
        ) VALUES (
            1, 600, 3, 5, 'tracker-runner-python:latest', 'tracker-runner-bash:latest'
        )
        ON CONFLICT (id) DO NOTHING
        """,
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_env_variables_task_key "
        "ON task_env_variables (task_id, key)",
    )
    op.execute(
        "ALTER TABLE llm_accounts "
        "ADD COLUMN IF NOT EXISTS rate_limit_resets_at TIMESTAMP WITH TIME ZONE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE llm_accounts DROP COLUMN IF EXISTS rate_limit_resets_at")
    op.execute("DROP INDEX IF EXISTS uq_task_env_variables_task_key")
    op.execute("DROP TABLE IF EXISTS system_settings")

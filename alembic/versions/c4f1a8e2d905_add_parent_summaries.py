"""add task_parent_summaries and parent summary enum values

Revision ID: c4f1a8e2d905
Revises: b7d4e2a91c3f
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4f1a8e2d905'
down_revision: Union[str, Sequence[str], None] = 'b7d4e2a91c3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_task_manual_request_queue_type_matches_payload"


def upgrade() -> None:
    """Upgrade schema."""
    # Новые значения enum должны быть закоммичены до того, как их прочитает
    # check-constraint ниже, — поэтому отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE manual_request_type ADD VALUE IF NOT EXISTS 'parent_summary'")
        op.execute("ALTER TYPE node_log_trigger_type ADD VALUE IF NOT EXISTS 'summary_for_child'")
        op.execute("ALTER TYPE node_log_trigger_type ADD VALUE IF NOT EXISTS 'parent_summary'")

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE parent_summary_status AS ENUM ('pending', 'ready', 'unavailable');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_parent_summaries (
            id UUID PRIMARY KEY,
            parent_task_id UUID NOT NULL REFERENCES tasks (id),
            child_task_id UUID NOT NULL UNIQUE REFERENCES tasks (id),
            status parent_summary_status NOT NULL,
            summary_text TEXT,
            unavailable_reason TEXT,
            manual_request_id UUID REFERENCES task_manual_request_queue (id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            completed_at TIMESTAMP WITH TIME ZONE,
            delivered_at TIMESTAMP WITH TIME ZONE
        )
        """,
    )
    op.execute(f"ALTER TABLE task_manual_request_queue DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"""
        ALTER TABLE task_manual_request_queue ADD CONSTRAINT {_CONSTRAINT} CHECK (
            (request_type = 'library_prompt' AND node_id IS NOT NULL AND raw_prompt_text IS NULL)
            OR (request_type IN ('freeform_prompt', 'parent_summary')
                AND raw_prompt_text IS NOT NULL AND node_id IS NULL)
        )
        """,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"ALTER TABLE task_manual_request_queue DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"""
        ALTER TABLE task_manual_request_queue ADD CONSTRAINT {_CONSTRAINT} CHECK (
            (request_type = 'library_prompt' AND node_id IS NOT NULL AND raw_prompt_text IS NULL)
            OR (request_type = 'freeform_prompt' AND raw_prompt_text IS NOT NULL AND node_id IS NULL)
        )
        """,
    )
    op.execute("DROP TABLE IF EXISTS task_parent_summaries")
    op.execute("DROP TYPE IF EXISTS parent_summary_status")
    # PostgreSQL не умеет удалять значения enum-типа: 'parent_summary',
    # 'summary_for_child' остаются в типах — записи с ними нужно убрать до
    # отката кода.

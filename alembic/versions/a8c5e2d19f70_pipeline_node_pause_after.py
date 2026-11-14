"""Default pause after a pipeline node, copied into the task snapshot."""

from alembic import op

revision = "a8c5e2d19f70"
down_revision = "e5c9a3d7f142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS pause_after boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE nodes DROP COLUMN IF EXISTS pause_after")

"""Профили Compose и история проверок задач."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a102b304c506"
down_revision = "f8c1a6d2b940"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("test_profile", postgresql.JSONB(), nullable=True))
    op.add_column("nodes", sa.Column("test_repository_id", sa.UUID(), nullable=True))
    op.add_column("nodes", sa.Column("test_check", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_nodes_test_repository",
        "nodes",
        "repositories",
        ["test_repository_id"],
        ["id"],
    )
    op.create_table(
        "test_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("task_id", sa.UUID(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("repository_id", sa.UUID(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("check", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("repository_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cleanup_status", sa.String(), nullable=False),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report_files", postgresql.JSONB(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_id", "idempotency_key"),
    )
    op.create_index("ix_test_runs_task_id", "test_runs", ["task_id"])
    op.create_index("ix_test_runs_status", "test_runs", ["status", "cleanup_status"])


def downgrade() -> None:
    op.drop_table("test_runs")
    op.drop_constraint("fk_nodes_test_repository", "nodes", type_="foreignkey")
    op.drop_column("nodes", "test_check")
    op.drop_column("nodes", "test_repository_id")
    op.drop_column("repositories", "test_profile")

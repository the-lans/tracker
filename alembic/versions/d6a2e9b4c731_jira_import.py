"""personal Jira connection on users, source Jira issue on tasks

Revision ID: d6a2e9b4c731
Revises: c3f8a1e5d924
Create Date: 2026-10-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd6a2e9b4c731'
down_revision: Union[str, Sequence[str], None] = 'c3f8a1e5d924'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS jira_url VARCHAR")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS jira_email VARCHAR")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS jira_token_encrypted TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_issue_url VARCHAR")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS jira_issue_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jira_token_encrypted")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jira_email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jira_url")

"""LLM proxy routing: provider accounts, switch thresholds, reasoning effort

Revision ID: a1d5f8c3e047
Revises: f4c2a8e6b913
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1d5f8c3e047'
down_revision: Union[str, Sequence[str], None] = 'f4c2a8e6b913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EFFORT_TYPE = "reasoning_effort"
_EFFORT_VALUES = "'low', 'medium', 'high', 'xhigh', 'max'"
_SWITCH_REASON_TYPE = "llm_switch_reason"
_SWITCH_REASON_VALUES = (
    "'start', 'kept', 'threshold_5h', 'threshold_week', 'rate_limited', "
    "'login_required', 'disabled', 'unsuitable', 'all_above_threshold'"
)
_DEFAULT_THRESHOLD_PCT = 93
_THRESHOLD_COLUMNS = ("llm_switch_threshold_5h_pct", "llm_switch_threshold_week_pct")


def _add_enum_values() -> None:
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE llm_account_status ADD VALUE IF NOT EXISTS 'login_required' "
            "BEFORE 'active'",
        )
        op.execute("ALTER TYPE remote_control_status ADD VALUE IF NOT EXISTS 'unavailable'")
    for type_name, values in (
        (_EFFORT_TYPE, _EFFORT_VALUES),
        (_SWITCH_REASON_TYPE, _SWITCH_REASON_VALUES),
    ):
        op.execute(
            f"""
            DO $$ BEGIN
                CREATE TYPE {type_name} AS ENUM ({values});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """,
        )


def _upgrade_llm_accounts() -> None:
    op.execute(
        f"""
        ALTER TABLE llm_accounts
            ADD COLUMN IF NOT EXISTS provider VARCHAR NOT NULL DEFAULT 'anthropic',
            ADD COLUMN IF NOT EXISTS cliproxy_credential VARCHAR,
            ADD COLUMN IF NOT EXISTS cliproxy_prefix VARCHAR,
            ADD COLUMN IF NOT EXISTS default_model VARCHAR,
            ADD COLUMN IF NOT EXISTS default_effort {_EFFORT_TYPE} NOT NULL DEFAULT 'high',
            ADD COLUMN IF NOT EXISTS switch_order INTEGER,
            ADD COLUMN IF NOT EXISTS usage_5h_pct NUMERIC(5, 2),
            ADD COLUMN IF NOT EXISTS usage_week_pct NUMERIC(5, 2),
            ADD COLUMN IF NOT EXISTS usage_5h_resets_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS usage_week_resets_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS usage_checked_at TIMESTAMP WITH TIME ZONE,
            ALTER COLUMN claude_config_dir DROP NOT NULL
        """,
    )
    # Прежние аккаунты входили в Claude в своём каталоге — в прокси их входа нет.
    op.execute(
        """
        UPDATE llm_accounts
        SET cliproxy_prefix = 'acc-' || left(replace(id::text, '-', ''), 12)
        WHERE cliproxy_prefix IS NULL
        """,
    )
    op.execute(
        """
        UPDATE llm_accounts SET switch_order = ordered.position
        FROM (
            SELECT id, row_number() OVER (PARTITION BY created_by ORDER BY created_at, id) AS position
            FROM llm_accounts
        ) AS ordered
        WHERE llm_accounts.id = ordered.id AND llm_accounts.switch_order IS NULL
        """,
    )
    op.execute("UPDATE llm_accounts SET status = 'login_required' WHERE cliproxy_credential IS NULL")
    op.execute(
        """
        ALTER TABLE llm_accounts
            ALTER COLUMN cliproxy_prefix SET NOT NULL,
            ALTER COLUMN switch_order SET NOT NULL
        """,
    )
    for constraint, definition in (
        ("llm_accounts_cliproxy_credential_key", "UNIQUE (cliproxy_credential)"),
        ("llm_accounts_cliproxy_prefix_key", "UNIQUE (cliproxy_prefix)"),
        (
            "uq_llm_accounts_owner_switch_order",
            "UNIQUE (created_by, switch_order) DEFERRABLE INITIALLY DEFERRED",
        ),
    ):
        op.execute(
            f"""
            DO $$ BEGIN
                ALTER TABLE llm_accounts ADD CONSTRAINT {constraint} {definition};
            EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL;
            END $$
            """,
        )


def _upgrade_users() -> None:
    for column in _THRESHOLD_COLUMNS:
        op.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column} INTEGER NOT NULL "
            f"DEFAULT {_DEFAULT_THRESHOLD_PCT}",
        )
        op.execute(
            f"""
            DO $$ BEGIN
                ALTER TABLE users ADD CONSTRAINT ck_users_{column}
                    CHECK ({column} BETWEEN 1 AND 100);
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """,
        )


def _upgrade_runs() -> None:
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS current_llm_account_id UUID "
        "REFERENCES llm_accounts (id)",
    )
    # Раздел 6.3: мост через прокси невозможен ни у одной задачи.
    op.execute("UPDATE tasks SET remote_control_status = 'unavailable'")
    op.execute(f"ALTER TABLE nodes ADD COLUMN IF NOT EXISTS reasoning_effort {_EFFORT_TYPE}")
    op.execute(
        f"""
        ALTER TABLE node_logs
            ADD COLUMN IF NOT EXISTS llm_account_id UUID REFERENCES llm_accounts (id),
            ADD COLUMN IF NOT EXISTS llm_model VARCHAR,
            ADD COLUMN IF NOT EXISTS reasoning_effort {_EFFORT_TYPE},
            ADD COLUMN IF NOT EXISTS llm_switch_reason {_SWITCH_REASON_TYPE}
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_node_logs_llm_account_id ON node_logs (llm_account_id)",
    )


def upgrade() -> None:
    """Upgrade schema."""
    _add_enum_values()
    _upgrade_llm_accounts()
    _upgrade_users()
    _upgrade_runs()


def downgrade() -> None:
    """Downgrade schema."""
    # Значения enum-типов PostgreSQL удалить не умеет: 'login_required' и
    # 'unavailable' остаются в типах, строки с ними возвращаются к прежним значениям.
    op.execute("UPDATE tasks SET remote_control_status = 'disconnected' "
               "WHERE remote_control_status = 'unavailable'")
    op.execute("UPDATE llm_accounts SET status = 'disabled' WHERE status = 'login_required'")
    op.execute("DROP INDEX IF EXISTS ix_node_logs_llm_account_id")
    op.execute(
        """
        ALTER TABLE node_logs
            DROP COLUMN IF EXISTS llm_account_id,
            DROP COLUMN IF EXISTS llm_model,
            DROP COLUMN IF EXISTS reasoning_effort,
            DROP COLUMN IF EXISTS llm_switch_reason
        """,
    )
    op.execute("ALTER TABLE nodes DROP COLUMN IF EXISTS reasoning_effort")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS current_llm_account_id")
    for column in _THRESHOLD_COLUMNS:
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {column}")
    # claude_config_dir остаётся nullable: у аккаунтов, заведённых через прокси, каталога нет.
    op.execute(
        """
        ALTER TABLE llm_accounts
            DROP CONSTRAINT IF EXISTS uq_llm_accounts_owner_switch_order,
            DROP COLUMN IF EXISTS provider,
            DROP COLUMN IF EXISTS cliproxy_credential,
            DROP COLUMN IF EXISTS cliproxy_prefix,
            DROP COLUMN IF EXISTS default_model,
            DROP COLUMN IF EXISTS default_effort,
            DROP COLUMN IF EXISTS switch_order,
            DROP COLUMN IF EXISTS usage_5h_pct,
            DROP COLUMN IF EXISTS usage_week_pct,
            DROP COLUMN IF EXISTS usage_5h_resets_at,
            DROP COLUMN IF EXISTS usage_week_resets_at,
            DROP COLUMN IF EXISTS usage_checked_at
        """,
    )
    op.execute(f"DROP TYPE IF EXISTS {_EFFORT_TYPE}")
    op.execute(f"DROP TYPE IF EXISTS {_SWITCH_REASON_TYPE}")

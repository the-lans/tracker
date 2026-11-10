"""
Контроль лимитов LLM-аккаунтов (раздел 19.7): ожидание сброса лимита,
момент старта 5-часового окна, стоимость хода, сжатие контекста и отметка
о сжатии в `node_logs`.

Только добавление (раздел 20.6): прежняя версия новых столбцов не читает, а
задачи в `awaiting_limit` откат переводит в `failed`/`refining` до перехода
на прежний код (`deploy/install.sh`). Столбец недельного порога
`users.llm_switch_threshold_week_pct` остаётся: его читает прежняя версия.
"""

from alembic import op

revision = "e5b81c4d2f97"
down_revision = "c7e4b19a3d60"
branch_labels = None
depends_on = None

_SWITCH_REASONS = ("window_planned", "window_balance", "week_exhausted")

# Из чата — обратно в `refining`, остальные — в `failed` с точкой перезапуска
# на ноде, которая ждала лимита.
_RESTORE_LIMIT_WAITS = (
    "UPDATE tasks SET "
    "status = CASE WHEN limit_wait_from_status::text = 'refining' "
    "THEN 'refining'::task_status ELSE 'failed'::task_status END, "
    "last_failed_order_index = CASE WHEN limit_wait_from_status::text = 'refining' "
    "THEN last_failed_order_index "
    "ELSE coalesce(limit_wait_order_index, last_failed_order_index) END "
    "WHERE status::text = 'awaiting_limit'"
)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'awaiting_limit'")
        for reason in _SWITCH_REASONS:
            op.execute(f"ALTER TYPE llm_switch_reason ADD VALUE IF NOT EXISTS '{reason}'")

    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS limit_wait_from_status task_status")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS limit_wait_until timestamptz")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS limit_wait_order_index integer")
    op.execute("ALTER TABLE llm_accounts ADD COLUMN IF NOT EXISTS window_started_at timestamptz")
    op.execute("ALTER TABLE llm_accounts ADD COLUMN IF NOT EXISTS turn_cost_pct numeric(5, 2)")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "llm_compact_on_switch boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE node_logs ADD COLUMN IF NOT EXISTS "
        "llm_context_compacted boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    # PostgreSQL не умеет удалять значения enum-типа: ждущие лимита задачи
    # уходят в статусы прежней версии (как откат в `deploy/install.sh`),
    # значения остаются в типах.
    op.execute(_RESTORE_LIMIT_WAITS)
    op.execute("ALTER TABLE node_logs DROP COLUMN IF EXISTS llm_context_compacted")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS llm_compact_on_switch")
    op.execute("ALTER TABLE llm_accounts DROP COLUMN IF EXISTS turn_cost_pct")
    op.execute("ALTER TABLE llm_accounts DROP COLUMN IF EXISTS window_started_at")
    for column in ("limit_wait_order_index", "limit_wait_until", "limit_wait_from_status"):
        op.execute(f"ALTER TABLE tasks DROP COLUMN IF EXISTS {column}")


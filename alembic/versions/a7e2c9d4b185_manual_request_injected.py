"""
Влитие промта из очереди в идущий ход (раздел 7.3): статус запроса `injected`.

Только добавление (раздел 20.6): прежняя версия значения не знает, поэтому
откат возвращает такие запросы в очередь.
"""

from alembic import op

revision = "a7e2c9d4b185"
down_revision = "e1a7c3b9d264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE manual_request_status ADD VALUE IF NOT EXISTS 'injected'")


def downgrade() -> None:
    # Значение enum не удаляется (раздел 20.6): запросы лишь возвращаются в очередь.
    op.execute(
        "UPDATE task_manual_request_queue SET status = 'queued' WHERE status::text = 'injected'"
    )

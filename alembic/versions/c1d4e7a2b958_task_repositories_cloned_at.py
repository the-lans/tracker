"""
Репозиторий задачи можно добавить после создания (разделы 3.1, 3.2):
`task_repositories.cloned_at` — когда воркер склонировал его в каталог задачи.

Только добавление (раздел 20.6): прежняя версия столбец не читает. У задач,
которые уже запускались или общались в чате, репозитории считаются
склонированными — удалить такую привязку нельзя.
"""

from alembic import op

revision = "c1d4e7a2b958"
down_revision = "37d3c9b76180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_repositories ADD COLUMN IF NOT EXISTS cloned_at timestamptz")
    op.execute(
        """
        UPDATE task_repositories SET cloned_at = now()
        FROM tasks
        WHERE tasks.id = task_repositories.task_id
          AND task_repositories.cloned_at IS NULL
          AND (
            tasks.status NOT IN ('new', 'refining', 'defined', 'ready', 'night_worker')
            OR tasks.session_id IS NOT NULL
            OR tasks.reset_at IS NOT NULL
          )
        """,
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_repositories DROP COLUMN IF EXISTS cloned_at")

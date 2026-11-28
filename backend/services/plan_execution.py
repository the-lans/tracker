"""Сохраняемые этапы планирования и реализации одной ноды."""

from __future__ import annotations

from db.models.enums import NodeLogStatus, PermissionMode
from db.models.logs import NodeLog

PLAN_PLANNING = "planning"
PLAN_ACCEPTED = "accepted"
PLAN_IMPLEMENTING = "implementing"
PLAN_COMPLETE = "complete"


def accept_plan_execution(log: NodeLog, *, mode: PermissionMode) -> None:
    """Принятие плана ещё не завершает ноду, которой предстоит реализация."""
    if log.plan_execution is None:
        return
    log.plan_execution = {
        "phase": PLAN_ACCEPTED,
        "plan": log.pending_plan_text,
        "permission_mode": mode.value,
    }
    log.status = NodeLogStatus.RUNNING
    log.finished_at = None


def implementation_prompt(plan: str, *, recovery_notice: str | None = None) -> str:
    prompt = (
        "План уже принят. Перейди к его реализации сейчас, в рамках текущей задачи. "
        "Не запрашивай принятие этого плана повторно и не переходи к следующему шагу "
        "пайплайна. Сначала проверь текущее состояние файлов: предыдущая попытка могла "
        "выполнить часть работы. Продолжи незавершённое, не повторяя уже выполненные "
        "неидемпотентные действия. Выполни необходимые проверки доступными средствами. "
        "При блокере укажи его явно; не утверждай, что работа выполнена. "
        "В конце сообщи результат реализации на русском.\n\nПринятый план:\n" + plan
    )
    return prompt + ("\n\n" + recovery_notice if recovery_notice else "")

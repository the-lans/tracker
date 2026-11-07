"""
Эндпоинты задачи (раздел 2.3, 2.4, 7, 8, 9.6, 13–15 ТЗ). Порядок подключения
важен: литеральные пути (`/awaiting-count`, `/active-sessions`) объявлены в
`crud` раньше `/{task_id}`.
"""

from fastapi import APIRouter

from api.tasks import artifacts, commands, crud, env_variables, lifecycle, manual, nodes

router = APIRouter()
for module in (crud, lifecycle, nodes, manual, commands, env_variables, artifacts):
    router.include_router(module.router)

__all__ = ["router"]

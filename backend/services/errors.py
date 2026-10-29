"""Единая иерархия исключений приложения (раздел 17.3 ТЗ).

Перехватывается middleware в main.py и приводится к стандартизированному
формату ответа API один раз, а не в каждом роутере отдельно.
"""

from __future__ import annotations


class AppError(Exception):
    """Базовый класс всех прикладных ошибок."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    """Ошибка валидации входных данных."""

    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    """Запрошенная сущность не найдена."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Конфликт состояния — например, попытка удалить используемую сущность
    (раздел 3.2 ТЗ) или нарушение compare-and-swap перехода статуса."""

    status_code = 409
    code = "conflict"


class PayloadTooLargeError(AppError):
    """Загружаемый файл больше допустимого (раздел 14.3 ТЗ, артефакты задачи)."""

    status_code = 413
    code = "payload_too_large"


class UnauthorizedError(AppError):
    """Отсутствует или недействителен токен сессии (раздел 19.1 ТЗ)."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """
    Роль пользователя не позволяет выполнить действие (раздел 19.2 ТЗ) или
    вход не разрешён (раздел 19.1 ТЗ).
    """

    status_code = 403
    code = "forbidden"


class ExternalServiceError(AppError):
    """Ошибка при обращении к внешней системе (GitLab API, MCP-сервер,
    Claude Agent SDK). ``is_transient`` разделяет временные сбои, подлежащие
    retry, от постоянных, требующих немедленного уведомления без бесполезных
    повторов (раздел 17.3 ТЗ)."""

    status_code = 502
    code = "external_service_error"

    def __init__(self, message: str, *, is_transient: bool) -> None:
        super().__init__(message)
        self.is_transient = is_transient

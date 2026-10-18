from services.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def test_app_error_carries_message() -> None:
    err = AppError("что-то пошло не так")
    assert err.message == "что-то пошло не так"
    assert err.status_code == 500
    assert err.code == "internal_error"


def test_validation_error_status_and_code() -> None:
    err = ValidationError("плохие данные")
    assert err.status_code == 422
    assert err.code == "validation_error"


def test_not_found_error_status_and_code() -> None:
    err = NotFoundError("не найдено")
    assert err.status_code == 404
    assert err.code == "not_found"


def test_conflict_error_status_and_code() -> None:
    err = ConflictError("конфликт")
    assert err.status_code == 409
    assert err.code == "conflict"


def test_external_service_error_transient_flag() -> None:
    transient = ExternalServiceError("сеть недоступна", is_transient=True)
    permanent = ExternalServiceError("доступ запрещён", is_transient=False)
    assert transient.is_transient is True
    assert permanent.is_transient is False
    assert transient.status_code == 502


def test_unauthorized_error_status_and_code() -> None:
    err = UnauthorizedError("нет токена")
    assert err.status_code == 401
    assert err.code == "unauthorized"


def test_forbidden_error_status_and_code() -> None:
    err = ForbiddenError("недостаточно прав")
    assert err.status_code == 403
    assert err.code == "forbidden"

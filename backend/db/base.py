from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей — используется Alembic для autogenerate."""

"""Общие фикстуры (раздел 21.1 ТЗ).

Переменные окружения для тестов задаются здесь, ДО импорта прикладных
модулей (некоторые из них — например ``db.session``, ``services.crypto``,
``tasks.celery_app`` — читают ``os.environ`` на уровне модуля).

Postgres для integration-тестов поднимается автоматически через
docker-compose (тот же способ, которым проверялась первая миграция) —
пропускается, если тестовая БД уже доступна на 55432 (например, поднята
вручную разработчиком заранее).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient

    from db.models.users import User

_TEST_REDIS_PORT = 55379
_TEST_REDIS_PASSWORD = "testpass"

os.environ.setdefault("SECRET_ENCRYPTION_KEY", "pytest-only-key-not-a-real-secret")
os.environ.setdefault("SESSION_SECRET_KEY", "pytest-only-session-key-not-a-real-secret")
os.environ.setdefault(
    "REDIS_URL",
    f"redis://:{_TEST_REDIS_PASSWORD}@localhost:{_TEST_REDIS_PORT}/0",
)
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("VAPID_PUBLIC_KEY", "test-vapid-public-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-vapid-private-key")
os.environ.setdefault("VAPID_CLAIMS_EMAIL", "admin@example.com")

_TEST_PG_PORT = 55432
_TEST_DATABASE_URL = (
    f"postgresql+asyncpg://tracker:testpass@localhost:{_TEST_PG_PORT}/tracker"
)
os.environ.setdefault("DATABASE_URL", _TEST_DATABASE_URL)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import redis  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy.orm import Session, SessionTransaction  # noqa: E402

from tests.worker_support import WorkerEnv, install_worker_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
_PG_CONTAINER_NAME = "tracker_pg_test"
_REDIS_CONTAINER_NAME = "tracker_redis_test"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[None]:
    """Одноразовый Postgres для тестовой сессии (раздел 21.1: integration-тесты
    требуют реальной работы с БД, не мока). Поднимается через docker-compose —
    то же самое, чем на этапе 2 плана проверялась первая миграция."""
    started_here = False
    if not _port_open(_TEST_PG_PORT):
        started_here = True
        subprocess.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "-d",
                "--publish",
                f"{_TEST_PG_PORT}:5432",
                "--name",
                _PG_CONTAINER_NAME,
                "-e",
                "POSTGRES_USER=tracker",
                "-e",
                "POSTGRES_PASSWORD=testpass",
                "-e",
                "POSTGRES_DB=tracker",
                "postgres",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        for _ in range(60):
            if _port_open(_TEST_PG_PORT):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Postgres-контейнер для тестов не поднялся за 30с")
        # pg_isready внутри контейнера может отстать от открытия TCP-порта.
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", _PG_CONTAINER_NAME, "pg_isready", "-U", "tracker"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)

    yield

    if started_here:
        subprocess.run(["docker", "stop", _PG_CONTAINER_NAME], capture_output=True)


def _redis_responds() -> bool:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
    finally:
        client.close()


@pytest.fixture(scope="session")
def redis_container() -> Iterator[None]:
    """Одноразовый Redis для тестовой сессии (раздел 21.1) — тот же паттерн,
    что и ``postgres_container``.

    ``docker-compose.yml`` задаёт пароль Redis через ``command: ["redis-server",
    "--requirepass", "${REDIS_PASSWORD}"]`` — это подставляется docker compose
    из переменных ОКРУЖЕНИЯ ПРОЦЕССА при разборе файла, а не из ``-e`` флагов
    контейнера (в отличие от `POSTGRES_USER`/`POSTGRES_PASSWORD`, которые
    читает entrypoint-скрипт postgres из фактического env контейнера) —
    поэтому пароль передаётся через ``env=`` самого `subprocess.run`.
    """
    started_here = False
    if not _port_open(_TEST_REDIS_PORT):
        started_here = True
        subprocess.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "-d",
                "--publish",
                f"{_TEST_REDIS_PORT}:6379",
                "--name",
                _REDIS_CONTAINER_NAME,
                "redis",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            env={**os.environ, "REDIS_PASSWORD": _TEST_REDIS_PASSWORD},
        )
        # Порт публикует docker-proxy раньше, чем Redis начинает принимать
        # соединения, — готовность проверяется ответом на PING.
        for _ in range(60):
            if _redis_responds():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Redis-контейнер для тестов не поднялся за 30с")

    yield

    if started_here:
        subprocess.run(["docker", "stop", _REDIS_CONTAINER_NAME], capture_output=True)


@pytest_asyncio.fixture
async def redis_client(redis_container: None) -> AsyncIterator[Redis]:
    """Клиент Redis для одного теста; база очищается до и после теста."""
    client = Redis.from_url(os.environ["REDIS_URL"])
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture(scope="session")
def run_migrations(postgres_container: None) -> None:
    """Применяет все миграции один раз на тестовую БД перед прогоном тестов."""
    # sys.executable — тот же venv, которым запущен pytest; голое "alembic"
    # не гарантированно есть в PATH (venv может быть не активирован).
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT / "backend",
        check=True,
        env={**os.environ},
    )


@pytest_asyncio.fixture
async def db_session(run_migrations: None) -> AsyncIterator[AsyncSession]:
    """Сессия БД для одного теста — обёрнута в транзакцию, которая
    откатывается после теста, чтобы тесты не влияли друг на друга.

    Паттерн — рекомендованный SQLAlchemy 2.0 для тестов ("Joining a Session
    into an External Transaction"): без предварительного SAVEPOINT и
    слушателя, восстанавливающего его после каждого commit/flush сессии,
    второй и последующий flush в одном тесте падают с asyncpg
    ``InterfaceError: another operation is in progress`` — ORM-сессия
    рассчитывает, что вложенная транзакция всегда есть, во что нестись.
    """
    from db.session import engine

    async with engine.connect() as connection:
        await connection.begin()
        await connection.begin_nested()
        # expire_on_commit=False — как в реальном db.session.async_session_factory:
        # без этого объекты, полученные ДО commit() (например, строки, выбранные
        # оркестратором один раз для итерации), становятся expired и требуют
        # синхронного lazy-load при следующем обращении — падает с
        # sqlalchemy.exc.MissingGreenlet вне контекста await.
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

        @sa.event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sync_session: Session, transaction: SessionTransaction) -> None:
            if connection.closed:
                return
            if not connection.in_nested_transaction():
                sync_connection = connection.sync_connection
                assert sync_connection is not None
                sync_connection.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()


@pytest.fixture(autouse=True)
def _celery_eager() -> None:
    """Celery-задачи выполняются синхронно в тестах (раздел 21.1)."""
    from tasks.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def user_files_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Артефакты задач (раздел 14.3) — во временном каталоге, а не в рабочей директории."""
    root = tmp_path / "user-files"
    monkeypatch.setenv("TRACKER_USER_FILES_ROOT", str(root))
    return root


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент против реального `main.app` (раздел 21.1 — интеграционные
    тесты API, не мок роутера) — `Depends(get_session)` подменён на
    `db_session` этого теста, чтобы запрос и тест видели одну транзакцию.

    Используется `httpx.ASGITransport` + `AsyncClient`, а НЕ `TestClient`:
    `TestClient` гоняет ASGI-приложение в отдельном потоке/event loop'е
    (anyio-портал) — тот же класс проблем с asyncpg, что уже описан у
    `db_session` выше (соединение привязано к своему loop'у). `AsyncClient`
    выполняется в том же (сессионном) event loop'е, что и сама фикстура.
    """
    from httpx import ASGITransport, AsyncClient

    from db.session import get_session
    from main import app

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def current_user(db_session: AsyncSession) -> User:
    """Обычный (не admin) пользователь, авторизованный `api_client`ом по
    умолчанию через переопределение `get_current_user` (см. `authed_client`)."""
    import uuid as uuid_module

    from db.models.enums import UserRole
    from db.models.users import User

    user = User(
        id=uuid_module.uuid4(),
        email=f"{uuid_module.uuid4()}@example.com",
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def authed_client(
    api_client: AsyncClient,
    current_user: User,
) -> AsyncIterator[AsyncClient]:
    """`api_client`, у которого `get_current_user` подменён на фикстуру
    `current_user` — тесты `api/tasks.py` проверяют бизнес-логику эндпоинтов,
    не сам механизм проверки Bearer-токена (тот покрыт `test_api_dependencies.py`
    и `test_api_auth.py` отдельно)."""
    from api.dependencies import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        yield api_client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Пользователь с ролью admin — для тестов эндпоинтов раздела 15.5
    (административная часть), защищённых `Depends(require_admin)`."""
    import uuid as uuid_module

    from db.models.enums import UserRole
    from db.models.users import User

    user = User(
        id=uuid_module.uuid4(),
        email=f"{uuid_module.uuid4()}@example.com",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_client(
    api_client: AsyncClient,
    admin_user: User,
) -> AsyncIterator[AsyncClient]:
    """`api_client`, у которого и `get_current_user`, и `require_admin`
    подменены на фикстуру `admin_user` — покрывает эндпоинты, доступные
    только администратору (раздел 19.2 ТЗ)."""
    from api.dependencies import get_current_user, require_admin
    from main import app

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        yield api_client
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def worker_env(
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkerEnv:
    """Зависимости воркера сессии подменены (`tests/worker_support.py`)."""
    return install_worker_env(
        db_session=db_session,
        redis_client=redis_client,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

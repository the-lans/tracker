"""
SFTP-шлюз целиком (раздел 14.3, 19.2, 19.3 ТЗ, решение №18 плана): настоящий
SSH-сервер на свободном порту и клиент `asyncssh` с ключом пользователя.
"""

from __future__ import annotations

import asyncio
import stat
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncssh
import pytest
import pytest_asyncio
import sqlalchemy as sa

from db.models.enums import UserRole
from db.models.tasks import Task
from sftp_gateway import auth as auth_module
from sftp_gateway.auth import ConnectionLimiter
from sftp_gateway.config import GatewayConfig
from sftp_gateway.host_key import load_or_create_host_key
from sftp_gateway.server import check_database, start_server
from tests.factories import SAMPLE_ED25519_KEY, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_POLL_ATTEMPTS = 50
_POLL_INTERVAL_SECONDS = 0.02


@dataclass
class Gateway:
    port: int
    config: GatewayConfig
    audit: list[dict[str, Any]]


@dataclass
class SftpUser:
    user: User
    key: asyncssh.SSHKey
    username: str


Connect = Callable[..., Awaitable[asyncssh.SSHClientConnection]]


async def _drain_background_writes() -> None:
    """
    Тесты делят одну сессию БД со шлюзом, поэтому фоновая запись входа
    (`auth._in_background`) должна завершиться до следующего обращения к ней.
    """
    while auth_module._background_tasks:
        await asyncio.gather(*auth_module._background_tasks)


@pytest_asyncio.fixture
async def gateway(
    db_session: AsyncSession,
    tmp_path: Path,
    user_files_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Gateway]:
    audit: list[dict[str, Any]] = []

    async def record_app_log(**fields: Any) -> None:
        audit.append(fields)

    monkeypatch.setattr(auth_module, "write_app_log", record_app_log)

    @asynccontextmanager
    async def shared_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    config = GatewayConfig(
        repos_root=tmp_path / "repos",
        user_files_root=user_files_root,
        host_key_path=tmp_path / "host-keys" / "ssh_host_ed25519_key",
        port=0,
    )
    acceptor = await start_server(
        config=config,
        session_factory=shared_session,
        host_key=load_or_create_host_key(config.host_key_path),
        host="127.0.0.1",
    )
    try:
        yield Gateway(port=acceptor.get_port(), config=config, audit=audit)
    finally:
        acceptor.close()
        await acceptor.wait_closed()
        await _drain_background_writes()


@pytest.fixture
def connect(gateway: Gateway) -> Connect:
    async def _connect(username: str, **options: Any) -> asyncssh.SSHClientConnection:
        try:
            return await asyncssh.connect(
                "127.0.0.1",
                gateway.port,
                username=username,
                known_hosts=None,
                agent_path=None,
                **options,
            )
        finally:
            await _drain_background_writes()

    return _connect


async def _sftp_user(db_session: AsyncSession, *, role: UserRole = UserRole.USER) -> SftpUser:
    key = asyncssh.generate_private_key("ssh-ed25519")
    user = await make_user(db_session, role=role)
    username = f"dev-{uuid.uuid4().hex[:6]}"
    user.os_username = username
    user.ssh_public_key = key.export_public_key().decode().strip()
    await db_session.flush()
    return SftpUser(user=user, key=key, username=username)


async def _task(db_session: AsyncSession, owner_id: uuid.UUID) -> Task:
    task = Task(code=f"RR-{uuid.uuid4().hex[:6]}", title="t", description="d", created_by=owner_id)
    db_session.add(task)
    await db_session.flush()
    return task


@asynccontextmanager
async def _sftp(connect: Connect, sftp_user: SftpUser) -> AsyncIterator[asyncssh.SFTPClient]:
    async with (
        await connect(sftp_user.username, client_keys=[sftp_user.key]) as conn,
        conn.start_sftp_client() as sftp,
    ):
        yield sftp


async def _wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(_POLL_ATTEMPTS):
        if condition():
            return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


class TestLogin:
    async def test_success_is_recorded(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)

        async with _sftp(connect, sftp_user) as sftp:
            assert await sftp.listdir("/") == [".", ".."]

        await _wait_for(lambda: bool(gateway.audit))
        await db_session.refresh(sftp_user.user)
        assert sftp_user.user.ssh_key_last_used_at is not None
        assert gateway.audit[0]["source"] == "sftp"
        assert gateway.audit[0]["context"]["username"] == sftp_user.username

    @pytest.mark.parametrize("case", ["other_key", "blocked"])
    async def test_rejected_and_audited(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
        case: str,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        key = sftp_user.key
        if case == "other_key":
            key = asyncssh.generate_private_key("ssh-ed25519")
        else:
            sftp_user.user.is_active = False
            await db_session.flush()

        with pytest.raises(asyncssh.PermissionDenied):
            await connect(sftp_user.username, client_keys=[key])

        await _wait_for(lambda: bool(gateway.audit))
        assert [entry["context"]["username"] for entry in gateway.audit] == [sftp_user.username]
        assert sftp_user.user.ssh_key_last_used_at is None

    async def test_touch_failure_still_audited(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken_touch(*_args: Any, **_kwargs: Any) -> None:
            raise sa.exc.OperationalError("UPDATE users", {}, Exception("db down"))

        monkeypatch.setattr(auth_module, "touch_ssh_key_usage", broken_touch)
        sftp_user = await _sftp_user(db_session)

        async with _sftp(connect, sftp_user) as sftp:
            assert await sftp.listdir("/") == [".", ".."]

        await _wait_for(lambda: bool(gateway.audit))
        assert gateway.audit[0]["context"]["username"] == sftp_user.username

    async def test_unknown_login_not_audited(self, gateway: Gateway, connect: Connect) -> None:
        with pytest.raises(asyncssh.PermissionDenied):
            await connect("nobody", client_keys=[asyncssh.generate_private_key("ssh-ed25519")])

        assert gateway.audit == []

    async def test_password_not_supported(
        self,
        db_session: AsyncSession,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)

        with pytest.raises(asyncssh.PermissionDenied):
            await connect(sftp_user.username, client_keys=None, password="secret")


class TestVisibility:
    async def test_user_sees_own_tasks(self, db_session: AsyncSession, connect: Connect) -> None:
        sftp_user = await _sftp_user(db_session)
        other = await make_user(db_session)
        own = await _task(db_session, sftp_user.user.id)
        foreign = await _task(db_session, other.id)

        async with _sftp(connect, sftp_user) as sftp:
            assert await sftp.listdir("/") == [".", "..", own.code]
            assert await sftp.listdir(f"/{own.code}") == [".", "..", "repos", "artifacts"]
            with pytest.raises(asyncssh.SFTPNoSuchFile):
                await sftp.listdir(f"/{foreign.code}/repos")

    async def test_admin_sees_all(self, db_session: AsyncSession, connect: Connect) -> None:
        admin = await _sftp_user(db_session, role=UserRole.ADMIN)
        other = await make_user(db_session)
        foreign = await _task(db_session, other.id)

        async with _sftp(connect, admin) as sftp:
            assert foreign.code in await sftp.listdir("/")

    async def test_block_applies_mid_session(
        self,
        db_session: AsyncSession,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        own = await _task(db_session, sftp_user.user.id)

        async with _sftp(connect, sftp_user) as sftp:
            assert own.code in await sftp.listdir("/")
            sftp_user.user.is_active = False
            await db_session.flush()

            assert await sftp.listdir("/") == [".", ".."]
            with pytest.raises(asyncssh.SFTPNoSuchFile):
                await sftp.listdir(f"/{own.code}/artifacts")

    @pytest.mark.parametrize(
        "fields",
        [
            {"ssh_public_key": None},
            {"ssh_public_key": SAMPLE_ED25519_KEY},
            {"os_username": "renamed-login"},
        ],
        ids=["key_removed", "key_replaced", "login_changed"],
    )
    async def test_key_change_applies_mid_session(
        self,
        db_session: AsyncSession,
        connect: Connect,
        fields: dict[str, object],
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        own = await _task(db_session, sftp_user.user.id)

        async with _sftp(connect, sftp_user) as sftp:
            assert own.code in await sftp.listdir("/")
            for name, value in fields.items():
                setattr(sftp_user.user, name, value)
            await db_session.flush()

            assert await sftp.listdir("/") == [".", ".."]
            with pytest.raises(asyncssh.SFTPNoSuchFile):
                await sftp.open(f"/{own.code}/artifacts/after.txt", "w")


class TestReposReadOnly:
    async def test_read_allowed_write_denied(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)
        repo_dir = gateway.config.repos_root / task.code / "app"
        repo_dir.mkdir(parents=True)
        (repo_dir / "README.md").write_text("# app")
        base = f"/{task.code}/repos/app"

        async with _sftp(connect, sftp_user) as sftp:
            async with sftp.open(f"{base}/README.md") as file:
                assert await file.read() == "# app"
                # Права меняются и через открытый дескриптор (fsetstat) — тоже отказ.
                with pytest.raises(asyncssh.SFTPPermissionDenied):
                    await file.chmod(0o777)

            denied: list[Callable[[], Awaitable[object]]] = [
                lambda: sftp.open(f"{base}/README.md", "w"),
                lambda: sftp.open(f"{base}/new.txt", "w"),
                lambda: sftp.remove(f"{base}/README.md"),
                lambda: sftp.mkdir(f"{base}/dir"),
                lambda: sftp.chmod(f"{base}/README.md", 0o777),
                lambda: sftp.rename(f"{base}/README.md", f"{base}/moved.md"),
            ]
            for operation in denied:
                with pytest.raises(asyncssh.SFTPPermissionDenied):
                    await operation()

        assert (repo_dir / "README.md").read_text() == "# app"
        assert stat.S_IMODE((repo_dir / "README.md").stat().st_mode) != 0o777
        assert sorted(path.name for path in repo_dir.iterdir()) == ["README.md"]


class TestArtifacts:
    async def test_write_read_rename_delete(
        self,
        db_session: AsyncSession,
        user_files_root: Path,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)
        base = f"/{task.code}/artifacts"

        async with _sftp(connect, sftp_user) as sftp:
            await sftp.mkdir(f"{base}/docs")
            async with sftp.open(f"{base}/docs/spec.md", "w") as file:
                await file.write("# spec")
            await sftp.rename(f"{base}/docs/spec.md", f"{base}/docs/final.md")
            assert await sftp.listdir(f"{base}/docs") == [".", "..", "final.md"]
            assert (user_files_root / task.code / "docs" / "final.md").read_text() == "# spec"

            await sftp.remove(f"{base}/docs/final.md")
            await sftp.rmdir(f"{base}/docs")

        assert list((user_files_root / task.code).iterdir()) == []

    async def test_remove_and_rename_act_on_symlink(
        self,
        db_session: AsyncSession,
        user_files_root: Path,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)
        directory = user_files_root / task.code
        directory.mkdir(parents=True)
        (directory / "report.txt").write_text("report")
        (directory / "latest").symlink_to("report.txt")
        (directory / "previous").symlink_to("report.txt")
        base = f"/{task.code}/artifacts"

        async with _sftp(connect, sftp_user) as sftp:
            await sftp.remove(f"{base}/latest")
            await sftp.rename(f"{base}/previous", f"{base}/old")

        assert sorted(path.name for path in directory.iterdir()) == ["old", "report.txt"]
        assert (directory / "old").is_symlink()
        assert (directory / "report.txt").read_text() == "report"

    async def test_links_denied(self, db_session: AsyncSession, connect: Connect) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)
        base = f"/{task.code}/artifacts"

        async with _sftp(connect, sftp_user) as sftp:
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.symlink("/etc/passwd", f"{base}/passwd")

    async def test_rename_between_tasks_denied(
        self,
        db_session: AsyncSession,
        connect: Connect,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        first = await _task(db_session, sftp_user.user.id)
        second = await _task(db_session, sftp_user.user.id)

        async with _sftp(connect, sftp_user) as sftp:
            async with sftp.open(f"/{first.code}/artifacts/a.txt", "w") as file:
                await file.write("a")
            source = f"/{first.code}/artifacts/a.txt"
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.rename(source, f"/{second.code}/artifacts/a.txt")


class TestPathEscape:
    async def test_symlink_outside_hidden_and_denied(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
        tmp_path: Path,
    ) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        (secret_dir / "token.txt").write_text("secret")
        task_dir = gateway.config.repos_root / task.code
        task_dir.mkdir(parents=True)
        (task_dir / "escape").symlink_to(secret_dir)
        (task_dir / "real.txt").write_text("ok")
        (task_dir / "alias.txt").symlink_to(task_dir / "real.txt")

        async with _sftp(connect, sftp_user) as sftp:
            names = await sftp.listdir(f"/{task.code}/repos")
            assert sorted(names) == [".", "..", "alias.txt", "real.txt"]
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.open(f"/{task.code}/repos/escape/token.txt")
            attrs = await sftp.lstat(f"/{task.code}/repos/alias.txt")
            assert attrs.permissions is not None
            assert stat.S_ISREG(attrs.permissions)

    async def test_dotdot_stays_in_root(self, db_session: AsyncSession, connect: Connect) -> None:
        sftp_user = await _sftp_user(db_session)
        task = await _task(db_session, sftp_user.user.id)

        async with _sftp(connect, sftp_user) as sftp:
            assert await sftp.realpath(f"/{task.code}/artifacts/../../..") == "/"
            with pytest.raises(asyncssh.SFTPNoSuchFile):
                await sftp.listdir(f"/{task.code}/artifacts/../../etc")


class TestNoShell:
    @pytest.mark.parametrize("command", ["ls /", None], ids=["exec", "shell"])
    async def test_rejected(
        self,
        db_session: AsyncSession,
        connect: Connect,
        command: str | None,
    ) -> None:
        sftp_user = await _sftp_user(db_session)

        async with await connect(sftp_user.username, client_keys=[sftp_user.key]) as conn:
            with pytest.raises(asyncssh.Error):
                result = await conn.run(command, check=True, timeout=5)
                assert result.exit_status != 0

    async def test_port_forwarding_rejected(
        self,
        db_session: AsyncSession,
        gateway: Gateway,
        connect: Connect,
    ) -> None:
        """Даже к заведомо открытому порту (самого шлюза) проброс не открывается."""
        sftp_user = await _sftp_user(db_session)

        async with await connect(sftp_user.username, client_keys=[sftp_user.key]) as conn:
            with pytest.raises(asyncssh.ChannelOpenError):
                await conn.open_connection("127.0.0.1", gateway.port)
            with pytest.raises(asyncssh.ChannelListenError):
                await conn.forward_remote_port("127.0.0.1", 0, "127.0.0.1", gateway.port)


class TestCheckDatabase:
    async def test_passes(self, db_session: AsyncSession) -> None:
        @asynccontextmanager
        async def session() -> AsyncIterator[AsyncSession]:
            yield db_session

        await check_database(session)

    async def test_unavailable_raises(self) -> None:
        @asynccontextmanager
        async def session() -> AsyncIterator[AsyncSession]:
            raise sa.exc.OperationalError("connect", {}, Exception("auth failed"))
            yield  # pragma: no cover

        with pytest.raises(sa.exc.OperationalError):
            await check_database(session)


class TestConnectionLimiter:
    def test_per_ip_and_total(self) -> None:
        limiter = ConnectionLimiter(per_ip=1, total=2)

        assert limiter.acquire("10.0.0.1") is True
        assert limiter.acquire("10.0.0.1") is False
        assert limiter.acquire("10.0.0.2") is True
        assert limiter.acquire("10.0.0.3") is False
        limiter.release("10.0.0.1")
        assert limiter.acquire("10.0.0.1") is True


class TestHostKey:
    def test_created_once(self, tmp_path: Path) -> None:
        path = tmp_path / "keys" / "ssh_host_ed25519_key"

        first = load_or_create_host_key(path)
        second = load_or_create_host_key(path)

        assert first.get_fingerprint() == second.get_fingerprint()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.with_name(path.name + ".pub").read_text().startswith("ssh-ed25519 ")

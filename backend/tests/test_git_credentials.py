"""
Доступы Git: права, секреты, привязка к хосту и временная авторизация.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import http.server
import importlib.util
import shlex
import ssl
import subprocess
import threading
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import asyncssh
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.git_ops as git_ops
from api.git_credentials import CredentialInput, update_credential
from db.base import Base
from db.models.repositories import GitCredential, Repository
from db.models.users import User
from services.crypto import decrypt, encrypt
from services.errors import ConflictError, ValidationError
from services.git_credentials import git_host, resolve_credential
from services.git_ops import _deploy_key_env, _run_git
from tests.git_support import init_bare_origin


def credential(**overrides: str) -> GitCredential:
    return GitCredential(
        id=uuid.uuid4(),
        name="GitLab",
        kind="https_token",
        host="git.example.com",
        username="oauth2",
        secret_encrypted=encrypt("secret-token"),
        **overrides,
    )


class TestCredentialAPI:
    async def test_create_and_preserve_secret(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        r = await admin_client.post(
            "/git-credentials",
            json={
                "name": "GitLab",
                "kind": "https_token",
                "host": "git.example.com",
                "secret": "secret-token",
            },
        )
        assert r.status_code == 201
        assert "secret" not in r.text
        row = await db_session.get(GitCredential, uuid.UUID(r.json()["id"]))
        assert row is not None and decrypt(row.secret_encrypted) == "secret-token"
        r = await admin_client.put(
            "/git-credentials/" + str(row.id),
            json={
                "name": "Renamed",
                "kind": "https_token",
                "host": row.host,
            },
        )
        assert r.status_code == 200
        await db_session.refresh(row)
        assert decrypt(row.secret_encrypted) == "secret-token"

    async def test_regular_user_cannot_create(self, authed_client: AsyncClient) -> None:
        r = await authed_client.post(
            "/git-credentials",
            json={
                "name": "GitLab",
                "kind": "https_token",
                "host": "git.example.com",
                "secret": "token",
            },
        )
        assert r.status_code == 403

    async def test_binding_guards(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        row = credential()
        db_session.add(row)
        await db_session.flush()
        body = dict(
            name="repo",
            git_url="https://git.example.com/org/repo.git",
            git_credential_id=str(row.id),
        )
        r = await admin_client.post("/repositories", json=body)
        assert r.status_code == 201
        assert r.json()["git_credential_id"] == str(row.id)
        assert (await admin_client.delete("/git-credentials/" + str(row.id))).status_code == 409
        assert (
            await admin_client.put(
                "/git-credentials/" + str(row.id),
                json={
                    "name": "Changed",
                    "kind": "https_token",
                    "host": "other.example.com",
                },
            )
        ).status_code == 409

    @pytest.mark.parametrize(
        "url",
        [
            "https://other.example.com/r.git",
            "git@git.example.com:org/r.git",
            "https://oauth2:token@git.example.com/r.git",
        ],
    )
    async def test_incompatible_url(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        url: str,
    ) -> None:
        row = credential()
        db_session.add(row)
        await db_session.flush()
        response = await admin_client.post(
            "/repositories",
            json={
                "name": "repo",
                "git_url": url,
                "git_credential_id": str(row.id),
            },
        )
        assert response.status_code == 422

    async def test_public_repository(self, authed_client: AsyncClient) -> None:
        r = await authed_client.post(
            "/repositories", json={"name": "public", "git_url": "https://git.example.com/r.git"}
        )
        assert r.status_code == 201 and r.json()["git_credential_id"] is None

    async def test_check_hides_secrets(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        row = credential()
        db_session.add(row)
        await db_session.flush()
        run = AsyncMock(return_value=(0, "refs", ""))
        monkeypatch.setattr(git_ops, "_run_git", run)
        endpoint = f"/git-credentials/{row.id}/check"
        body = {"git_url": "https://git.example.com/team/repo.git"}
        response = await admin_client.post(endpoint, json=body)
        assert response.status_code == 200 and response.json() == {"read_access": True}
        assert run.call_args.args[:1] == ("ls-remote",)
        assert not Path(run.call_args.kwargs["env"]["GIT_ASKPASS"]).exists()
        run.return_value = (128, "", "server echoed secret-token")
        response = await admin_client.post(endpoint, json=body)
        assert response.status_code == 422 and "secret-token" not in response.text
        run.reset_mock()
        response = await admin_client.post(
            endpoint, json={"git_url": "https://other.example.com/r.git"}
        )
        assert response.status_code == 422
        run.assert_not_called()

    async def test_invalid_key_and_delete(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        r = await admin_client.post(
            "/git-credentials",
            json={
                "name": "SSH",
                "kind": "ssh_key",
                "host": "git.example.com",
                "secret": "not-a-key",
            },
        )
        assert r.status_code == 422 and "not-a-key" not in r.text
        row = credential()
        db_session.add(row)
        await db_session.flush()
        assert (await admin_client.delete("/git-credentials/" + str(row.id))).status_code == 204

    async def test_user_permissions(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        row = credential()
        db_session.add(row)
        await db_session.flush()
        r = await authed_client.get("/git-credentials")
        assert (
            r.status_code == 200
            and "secret-token" not in r.text
            and "secret_encrypted" not in r.text
        )
        assert (
            await authed_client.post(
                "/repositories",
                json={
                    "name": "repo",
                    "git_url": "https://git.example.com/team/r.git",
                    "git_credential_id": str(row.id),
                },
            )
        ).status_code == 201
        assert (await authed_client.delete("/git-credentials/" + str(row.id))).status_code == 403
        assert (
            await authed_client.post(
                "/git-credentials/" + str(row.id) + "/check",
                json={
                    "git_url": "https://git.example.com/team/r.git",
                },
            )
        ).status_code == 403


class TestGitAuthentication:
    @pytest.mark.parametrize(
        ("prompt", "expected"),
        [
            ("Username for 'https://git.example.com': ", "oauth2"),
            ("Password for 'https://oauth2@git.example.com': ", "secret-token"),
        ],
        ids=["username", "password"],
    )
    async def test_askpass(self, prompt: str, expected: str) -> None:
        repository = Repository(
            git_url="https://git.example.com/org/repo.git", git_credential=credential()
        )
        async with _deploy_key_env(repository) as env:
            helper = Path(env["GIT_ASKPASS"])
            assert "secret-token" not in str(env)
            assert helper.stat().st_mode & 0o777 == 0o700
            result = subprocess.run([str(helper), prompt], env=env, capture_output=True, text=True)
            assert result.returncode == 0 and result.stdout.strip() == expected
            r = subprocess.run(
                [str(helper), "Password for 'https://evil.example.com': "],
                env=env,
                capture_output=True,
                text=True,
            )
            assert r.returncode != 0 and not r.stdout
            assert env["GIT_CONFIG_VALUE_0"] == ""
            assert env["GIT_CONFIG_VALUE_1"] == "false"
        assert not helper.exists() and not helper.parent.exists()

    async def test_cleanup_after_exception(self) -> None:
        repository = Repository(
            git_url="https://git.example.com/org/repo.git", git_credential=credential()
        )
        with pytest.raises(RuntimeError):
            async with _deploy_key_env(repository) as env:
                helper = Path(env["GIT_ASKPASS"])
                raise RuntimeError("test")
        assert not helper.parent.exists()

    async def test_ssh_credential_env(self) -> None:
        key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
        row = credential()
        row.kind = "ssh_key"
        row.secret_encrypted = encrypt(key)
        repo = Repository(git_url="git@git.example.com:org/r.git", git_credential=row)
        async with _deploy_key_env(repo) as env:
            assert "GIT_SSH_COMMAND" in env and "GIT_ASKPASS" not in env
            assert key not in str(env)

            path = Path(shlex.split(env["GIT_SSH_COMMAND"])[2])
            assert path.read_text() == key and path.stat().st_mode & 0o777 == 0o600
        assert not path.exists()

    async def test_authenticated_https(self, tmp_path: Path) -> None:
        """
        Реальный Git получает токен через askpass, сохраняя чистый origin URL.
        """

        origin = init_bare_origin(tmp_path)
        subprocess.run(["git", "--git-dir", str(origin), "update-server-info"], check=True)
        key, cert = tmp_path / "tls.key", tmp_path / "tls.crt"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )
        received: list[bool] = []
        expected = "Basic " + base64.b64encode(b"oauth2:secret-token").decode()

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self) -> None:
                authorized = self.headers.get("Authorization") == expected
                received.append(authorized)
                if not authorized:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="Git"')
                    self.end_headers()
                    return
                super().do_GET()

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            functools.partial(Handler, directory=str(origin.parent)),
        )
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        row = credential()
        row.host = "localhost"
        url = f"https://localhost:{server.server_port}/{origin.name}"
        repo = Repository(git_url=url, git_credential=row)
        try:
            async with _deploy_key_env(repo) as env:
                env["GIT_SSL_CAINFO"] = str(cert)
                code, output, _ = await _run_git("ls-remote", url, "HEAD", cwd=tmp_path, env=env)
                assert code == 0 and "HEAD" in output
                assert True in received
                assert "secret-token" not in repo.git_url
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestCredentialMigration:
    async def test_migration_drops_legacy_key(self, db_session: AsyncSession) -> None:
        path = (
            Path(__file__).resolve().parents[2] / "alembic/versions/c9e2f6a81034_git_credentials.py"
        )
        spec = importlib.util.spec_from_file_location("git_credential_migration", path)
        assert spec is not None and spec.loader is not None

        migration = types.ModuleType(spec.name)
        spec.loader.exec_module(migration)
        schema = "migration_" + uuid.uuid4().hex
        connection = await db_session.connection()
        encrypted = encrypt("legacy-private-key")
        await connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
        try:
            await connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
            await connection.execute(
                sa.text(
                    "CREATE TABLE repositories (id uuid PRIMARY KEY, name text NOT NULL, "
                    "git_url text NOT NULL, deploy_key_encrypted text NOT NULL)"
                )
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO repositories VALUES "
                    "(:id, 'legacy', 'git@git.example.com:team/r.git', :key)"
                ),
                {"id": uuid.uuid4(), "key": encrypted},
            )

            def upgrade(sync_connection: Connection) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()

            await connection.run_sync(upgrade)
            columns = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name='repositories' "
                    "AND column_name='deploy_key_encrypted'"
                ),
                {"schema": schema},
            )
            assert columns == 0
            assert await connection.scalar(sa.text("SELECT count(*) FROM git_credentials")) == 0
            assert await connection.scalar(sa.text("SELECT count(*) FROM repositories")) == 1

        finally:
            await connection.execute(sa.text("SET LOCAL search_path TO public"))
            await connection.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))


class TestCredentialLocking:
    async def test_binding_blocks_host_edit(self, scratch_database: str) -> None:
        """
        Два независимых соединения не могут сохранить несовместимую привязку.
        """

        engine = create_async_engine(scratch_database)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            row = credential()
            async with sessions() as session:
                session.add(row)
                await session.commit()
            async with sessions() as binding, sessions() as editing:
                # Имитируем паузу запроса создания после валидации, до commit.
                await resolve_credential(binding, row.id, "https://git.example.com/r.git")
                editing_pid = await editing.scalar(sa.text("SELECT pg_backend_pid()"))
                edit = asyncio.create_task(
                    update_credential(
                        row.id,
                        CredentialInput(
                            name="Changed", kind="https_token", host="other.example.com"
                        ),
                        editing,
                        User(),
                    )
                )
                try:
                    async with asyncio.timeout(5):
                        while True:
                            async with engine.connect() as observer:
                                waiting = await observer.scalar(
                                    sa.text(
                                        "SELECT wait_event_type FROM pg_stat_activity "
                                        "WHERE pid=:pid"
                                    ),
                                    {"pid": editing_pid},
                                )
                            if waiting == "Lock":
                                break
                            await asyncio.sleep(0.01)
                    assert not edit.done()
                    binding.add(
                        Repository(
                            name="bound",
                            git_url="https://git.example.com/r.git",
                            git_credential_id=row.id,
                        )
                    )
                    await binding.commit()
                    with pytest.raises(ConflictError):
                        await asyncio.wait_for(edit, 5)
                finally:
                    if not edit.done():
                        edit.cancel()
                        await asyncio.gather(edit, return_exceptions=True)
                await editing.rollback()
                async with sessions() as verify:
                    saved = await verify.get(GitCredential, row.id)
                    assert saved is not None and saved.host == "git.example.com"
        finally:
            await engine.dispose()


class TestGitURLs:
    @pytest.mark.parametrize(
        "url",
        [
            "https://[broken/repo.git",
            "https://git.example.com:bad/repo.git",
            "http://git.example.com/repo.git",
            "https://token@git.example.com/repo.git",
        ],
    )
    def test_invalid_urls(self, url: str) -> None:
        with pytest.raises(ValidationError):
            git_host(url)

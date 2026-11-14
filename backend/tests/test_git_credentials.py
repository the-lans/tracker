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
from typing import Any
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
from api.git_credentials import update_credential
from api.schemas import CredentialInput
from clients.gitlab import GitlabAccessDeniedError, GitlabClient
from db.base import Base
from db.models.repositories import GitCredential, Repository
from db.models.users import User
from db.session import async_session_factory
from services.crypto import decrypt, encrypt
from services.errors import ConflictError, ExternalServiceError, ValidationError
from services.git_credentials import (
    GitlabApiAccess,
    git_host,
    gitlab_api_access,
    next_ssh_known_hosts,
    resolve_credential,
)
from services.git_ops import _deploy_key_env, _run_git
from services.git_ssh import HOST_KEY_REJECTED_MESSAGE
from services.ssh_known_hosts import known_hosts_fingerprints
from tests.factories import build_git_credential
from tests.git_support import init_bare_origin


def credential(**overrides: Any) -> GitCredential:
    return build_git_credential(**overrides)


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
        assert response.status_code == 200
        assert response.json() == {
            "read_access": True,
            "gitlab_api": "disabled",
            "ssh_host_key_fingerprints": [],
        }
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


def _ssh_key() -> str:
    return asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()


class TestGitlabApiAccess:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            pytest.param(
                {"gitlab_api_enabled": True},
                GitlabApiAccess("https://git.example.com", "secret-token"),
                id="https: тот же токен",
            ),
            pytest.param(
                {"gitlab_api_enabled": True, "gitlab_api_token_encrypted": encrypt("api")},
                GitlabApiAccess("https://git.example.com", "api"),
                id="https: свой токен",
            ),
            pytest.param(
                {
                    "kind": "ssh_key",
                    "gitlab_api_enabled": True,
                    "gitlab_api_token_encrypted": encrypt("api"),
                    "gitlab_api_url": "https://git.example.com:8443/gitlab",
                },
                GitlabApiAccess("https://git.example.com:8443/gitlab", "api"),
                id="ssh: свой токен и адрес",
            ),
            pytest.param(
                {"kind": "ssh_key", "gitlab_api_enabled": True},
                None,
                id="ssh без токена",
            ),
            pytest.param({"gitlab_api_token_encrypted": encrypt("api")}, None, id="выключено"),
        ],
    )
    def test_access(self, overrides: dict[str, Any], expected: GitlabApiAccess | None) -> None:
        assert gitlab_api_access(credential(**overrides)) == expected

    def test_without_credential(self) -> None:
        assert gitlab_api_access(None) is None


class TestGitlabApiFields:
    _URL = "https://git.example.com/team/repo.git"

    @staticmethod
    def _body(**overrides: Any) -> dict[str, Any]:
        return {"name": "GitLab", "kind": "https_token", "host": "git.example.com"} | overrides

    @pytest.mark.parametrize(
        ("overrides", "status"),
        [
            pytest.param({"secret": "token", "gitlab_api_enabled": True}, 201, id="https"),
            pytest.param(
                {"kind": "ssh_key", "gitlab_api_enabled": True},
                422,
                id="ssh без токена API",
            ),
            pytest.param(
                {"kind": "ssh_key", "gitlab_api_enabled": True, "gitlab_api_token": "api"},
                201,
                id="ssh с токеном API",
            ),
            pytest.param(
                {"secret": "token", "gitlab_api_url": "gitlab.example.com"},
                422,
                id="адрес без схемы",
            ),
        ],
    )
    async def test_create(
        self,
        admin_client: AsyncClient,
        overrides: dict[str, Any],
        status: int,
    ) -> None:
        if overrides.get("kind") == "ssh_key":
            overrides = {"secret": _ssh_key()} | overrides
        response = await admin_client.post("/git-credentials", json=self._body(**overrides))
        assert response.status_code == status
        if status == 201:
            assert "gitlab_api_token" not in response.json()
            assert response.json()["gitlab_api_token_set"] is ("gitlab_api_token" in overrides)

    async def test_token_kept_and_removed(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        row = credential(gitlab_api_token_encrypted=encrypt("api-token"))
        db_session.add(row)
        await db_session.flush()
        endpoint = f"/git-credentials/{row.id}"
        body = self._body(gitlab_api_enabled=True, gitlab_api_url="https://git.example.com/gl/")

        kept = await admin_client.put(endpoint, json=body)
        assert kept.status_code == 200 and "api-token" not in kept.text
        assert kept.json() | {"id": None} == {
            "id": None,
            "name": "GitLab",
            "kind": "https_token",
            "host": "git.example.com",
            "username": "oauth2",
            "gitlab_api_enabled": True,
            "gitlab_api_url": "https://git.example.com/gl",
            "gitlab_api_token_set": True,
            "ssh_host_key_fingerprints": [],
        }
        removed = await admin_client.put(endpoint, json=body | {"gitlab_api_token": ""})
        assert removed.json()["gitlab_api_token_set"] is False
        await db_session.refresh(row)
        assert row.gitlab_api_token_encrypted is None

    async def test_switch_to_ssh_needs_token(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        row = credential(gitlab_api_enabled=True)
        db_session.add(row)
        await db_session.flush()
        body = self._body(kind="ssh_key", secret=_ssh_key(), gitlab_api_enabled=True)

        response = await admin_client.put(f"/git-credentials/{row.id}", json=body)

        assert response.status_code == 422
        assert "токен GitLab API" in response.text
        await db_session.refresh(row)
        assert row.kind == "https_token"

    @pytest.mark.parametrize(
        ("enabled", "outcome", "expected"),
        [
            pytest.param(False, None, "disabled", id="выключено"),
            pytest.param(True, None, "ok", id="ok"),
            pytest.param(
                True,
                GitlabAccessDeniedError("GitLab отклонил токен API (403)"),
                "GitLab отклонил токен API (403)",
                id="токен отклонён",
            ),
        ],
    )
    async def test_check(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        enabled: bool,
        outcome: Exception | None,
        expected: str,
    ) -> None:
        row = credential(gitlab_api_enabled=enabled)
        db_session.add(row)
        await db_session.flush()
        monkeypatch.setattr(git_ops, "_run_git", AsyncMock(return_value=(0, "refs", "")))
        get_project = AsyncMock(side_effect=outcome, return_value={})
        monkeypatch.setattr(GitlabClient, "get_project", get_project)

        response = await admin_client.post(
            f"/git-credentials/{row.id}/check",
            json={"git_url": self._URL},
        )

        assert response.json() == {
            "read_access": True,
            "gitlab_api": expected,
            "ssh_host_key_fingerprints": [],
        }
        assert get_project.await_count == int(enabled)
        if enabled:
            get_project.assert_awaited_with("team/repo")


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


def _host_key_line(host: str = "git.example.com") -> str:
    public_key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    return f"{host} {public_key.strip()}\n"


def _ssh_credential(**overrides: Any) -> GitCredential:
    key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
    return credential(kind="ssh_key", secret_encrypted=encrypt(key), **overrides)


def _ssh_repository(row: GitCredential) -> Repository:
    return Repository(git_url="git@git.example.com:org/r.git", git_credential=row)


def _ssh_options(env: dict[str, str]) -> dict[str, str]:
    words = shlex.split(env["GIT_SSH_COMMAND"])
    return dict(
        word.split("=", 1)
        for previous, word in zip(words, words[1:], strict=False)
        if previous == "-o"
    )


class TestHostKeyChecking:
    """
    Раздел 19.3: ключ Git-сервера проверяется всегда — сохранённый строго,
    без сохранённого запоминается при первом подключении; новые ключи сервера
    сохраняются, чтобы плановая смена ключей не останавливала задачи.
    """

    @pytest.mark.parametrize(("saved", "checking"), [(True, "yes"), (False, "accept-new")])
    async def test_ssh_options(self, *, saved: bool, checking: str) -> None:
        known_hosts = _host_key_line() if saved else None
        async with _deploy_key_env(
            _ssh_repository(_ssh_credential(ssh_known_hosts=known_hosts))
        ) as env:
            options = _ssh_options(env)
            file_text = Path(options["UserKnownHostsFile"]).read_text()

        assert options["StrictHostKeyChecking"] == checking
        assert options["UpdateHostKeys"] == "yes"
        assert file_text == (known_hosts or "")

    async def _commit(self, row: GitCredential) -> GitCredential:
        async with async_session_factory() as session:
            session.add(row)
            await session.commit()
        return row

    async def _saved(self, row: GitCredential) -> str | None:
        async with async_session_factory() as session:
            return await session.scalar(
                sa.select(GitCredential.ssh_known_hosts).where(GitCredential.id == row.id),
            )

    async def _cleanup(self, row: GitCredential) -> None:
        async with async_session_factory() as session:
            await session.execute(sa.delete(GitCredential).where(GitCredential.id == row.id))
            await session.commit()

    @pytest.mark.parametrize("saved", [False, True], ids=["first_use", "server_added_keys"])
    async def test_learned_keys_saved(self, run_migrations: None, *, saved: bool) -> None:
        previous = _host_key_line() if saved else None
        row = await self._commit(_ssh_credential(ssh_known_hosts=previous))
        learned = (previous or "") + _host_key_line()
        try:
            async with _deploy_key_env(_ssh_repository(row)) as env:
                # Так ssh дописывает ключи: accept-new и UpdateHostKeys.
                Path(_ssh_options(env)["UserKnownHostsFile"]).write_text(learned)

            assert await self._saved(row) == learned
        finally:
            await self._cleanup(row)

    async def test_not_saved_after_failed_operation(self, run_migrations: None) -> None:
        row = await self._commit(_ssh_credential())
        try:
            with pytest.raises(ExternalServiceError):
                async with _deploy_key_env(_ssh_repository(row)) as env:
                    Path(_ssh_options(env)["UserKnownHostsFile"]).write_text(_host_key_line())
                    raise ExternalServiceError("clone failed", is_transient=False)

            assert await self._saved(row) is None
        finally:
            await self._cleanup(row)

    async def test_concurrent_change_kept(self, run_migrations: None) -> None:
        """
        Ключ, который за время операции сохранили другие, не перезаписывается.
        """
        row = await self._commit(_ssh_credential())
        meanwhile = _host_key_line()
        try:
            async with _deploy_key_env(_ssh_repository(row)) as env:
                async with async_session_factory() as session:
                    await session.execute(
                        sa.update(GitCredential)
                        .where(GitCredential.id == row.id)
                        .values(ssh_known_hosts=meanwhile),
                    )
                    await session.commit()
                Path(_ssh_options(env)["UserKnownHostsFile"]).write_text(_host_key_line())

            assert await self._saved(row) == meanwhile
        finally:
            await self._cleanup(row)

    async def test_save_failure_does_not_break_git(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import services.git_credentials as git_credentials

        monkeypatch.setattr(
            git_credentials,
            "replace_ssh_known_hosts",
            AsyncMock(side_effect=sa.exc.OperationalError("UPDATE", {}, Exception("down"))),
        )
        async with _deploy_key_env(_ssh_repository(_ssh_credential())) as env:
            Path(_ssh_options(env)["UserKnownHostsFile"]).write_text(_host_key_line())

    async def test_rejected_host_key_explained(self, tmp_path: Path) -> None:
        fake_ssh = tmp_path / "ssh"
        fake_ssh.write_text("#!/bin/sh\necho 'Host key verification failed.' >&2\nexit 255\n")
        fake_ssh.chmod(0o700)
        env = git_ops._credential_environment() | {"GIT_SSH_COMMAND": str(fake_ssh)}

        with pytest.raises(ExternalServiceError) as exc_info:
            await _run_git("ls-remote", "git@git.example.com:org/r.git", cwd=tmp_path, env=env)

        assert exc_info.value.message == HOST_KEY_REJECTED_MESSAGE


class TestHostKeyAPI:
    """
    Раздел 19.3: ключ хоста в «Учётных данных Git» — вставить, сбросить, сверить.
    """

    def _body(self, **fields: Any) -> dict[str, Any]:
        return {"name": "SSH", "kind": "ssh_key", "host": "git.example.com", **fields}

    async def test_saved_and_fingerprint_shown(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        known_hosts = _host_key_line()
        key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()

        r = await admin_client.post(
            "/git-credentials",
            json=self._body(secret=key, ssh_known_hosts=known_hosts),
        )

        assert r.status_code == 201, r.text
        assert r.json()["ssh_host_key_fingerprints"] == known_hosts_fingerprints(known_hosts)
        row = await db_session.get(GitCredential, uuid.UUID(r.json()["id"]))
        assert row is not None and row.ssh_known_hosts == known_hosts

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({}, "kept"),
            ({"ssh_known_hosts": ""}, None),
            ({"host": "other.example.com"}, None),
        ],
        ids=["omitted_keeps", "empty_resets", "host_change_resets"],
    )
    async def test_update(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        fields: dict[str, str],
        expected: str | None,
    ) -> None:
        saved = _host_key_line()
        row = _ssh_credential(ssh_known_hosts=saved)
        db_session.add(row)
        await db_session.flush()

        r = await admin_client.put(f"/git-credentials/{row.id}", json=self._body(**fields))

        assert r.status_code == 200, r.text
        await db_session.refresh(row)
        assert row.ssh_known_hosts == (saved if expected == "kept" else expected)

    @pytest.mark.parametrize(
        "known_hosts",
        ["git.example.com ssh-ed25519 AAAAbroken", "только-хост", "# комментарий без ключей"],
    )
    async def test_invalid_rejected(self, admin_client: AsyncClient, known_hosts: str) -> None:
        key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()

        r = await admin_client.post(
            "/git-credentials",
            json=self._body(secret=key, ssh_known_hosts=known_hosts),
        )

        assert r.status_code == 422


class TestNextSshKnownHosts:
    """Раздел 19.3: какой ключ хоста остаётся у записи после сохранения."""

    @pytest.mark.parametrize(
        ("kind", "submitted", "server_changed", "expected"),
        [
            ("ssh_key", None, False, "stored"),
            ("ssh_key", None, True, None),
            ("ssh_key", "", False, None),
            ("ssh_key", "  ", True, None),
            ("ssh_key", "new", True, "new"),
            ("https_token", None, False, None),
            ("https_token", "new", False, None),
        ],
    )
    def test_rule(
        self,
        kind: str,
        submitted: str | None,
        expected: str | None,
        *,
        server_changed: bool,
    ) -> None:
        values = {"stored": _host_key_line(), "new": _host_key_line("other.example.com")}

        result = next_ssh_known_hosts(
            kind=kind,
            stored=values["stored"],
            submitted=values.get(submitted, submitted) if submitted is not None else None,
            server_changed=server_changed,
        )

        assert result == (values[expected] if expected is not None else None)

    def test_submitted_validated(self) -> None:
        with pytest.raises(ValidationError):
            next_ssh_known_hosts(
                kind="ssh_key",
                stored=None,
                submitted="только-хост",
                server_changed=False,
            )


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

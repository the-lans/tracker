"""
Стек docker-compose: LLM-прокси, шлюз и сеть сессий (разделы 19.3, 19.4,
19.7, 20.3 ТЗ), воркер бэкапа (раздел 20.4, 20.5) и рендер конфигурации
прокси `deploy/cliproxy/init.sh`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from services.backup.components import COMPONENTS
from tasks.celery_app import BACKUP_TO_S3, BACKUPS_QUEUE, VERIFY_S3_BACKUP, celery_app

REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = REPO_ROOT / "docker-compose.yml"
_CLIPROXY_DIR = REPO_ROOT / "deploy" / "cliproxy"
_SESSION_NETWORK = "${COMPOSE_PROJECT_NAME:-tracker}-llm-sessions"


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text())
    return loaded


def _volume_names(service: dict[str, Any]) -> set[str]:
    return {str(volume).split(":")[0] for volume in service.get("volumes", [])}


class TestBackupWorker:
    def test_own_queue_one_process(self, compose: dict[str, Any]) -> None:
        command = compose["services"]["backup-worker"]["command"]
        assert command[command.index("-Q") + 1] == BACKUPS_QUEUE
        assert command[command.index("--concurrency") + 1] == "1"

    def test_tasks_routed(self) -> None:
        routes = celery_app.conf.task_routes
        assert {routes[name]["queue"] for name in (BACKUP_TO_S3, VERIFY_S3_BACKUP)} == {
            BACKUPS_QUEUE,
        }

    def test_all_components_read_only(self, compose: dict[str, Any]) -> None:
        volumes = compose["services"]["backup-worker"]["volumes"]
        mounted = {
            str(volume).split(":/data/backup-src/")[1].split(":")[0]: str(volume)
            for volume in volumes
            if ":/data/backup-src/" in str(volume)
        }
        assert set(mounted) == {component.name for component in COMPONENTS} | {"env"}
        assert all(volume.endswith(":ro") for volume in mounted.values())


class TestBackendImages:
    def test_know_their_commit(self, compose: dict[str, Any]) -> None:
        """Коммит образа — версия в /api/health и в manifest.json копии (раздел 20.4)."""
        built = {
            name: service["build"]
            for name, service in compose["services"].items()
            if service.get("build", {}).get("dockerfile") == "backend/Dockerfile"
        }
        assert {"backend", "backup-worker", "worker", "beat", "sftp"} <= set(built)
        assert {
            name: build.get("args", {}).get("GIT_SHA") for name, build in built.items()
        } == dict.fromkeys(built, "${GIT_SHA:-unknown}")


class TestLlmProxy:
    def test_proxy_not_published(self, compose: dict[str, Any]) -> None:
        assert "ports" not in compose["services"]["cliproxy"]

    def test_proxy_built_from_pinned_tag(self, compose: dict[str, Any]) -> None:
        context = compose["services"]["cliproxy"]["build"]["context"]
        assert context == "https://github.com/router-for-me/CLIProxyAPI.git#${CLIPROXY_VERSION}"

    @pytest.mark.parametrize(
        ("variable", "value"),
        [
            # Админка «LLM-прокси» показывает версию из окружения backend (раздел 15.5).
            ("CLIPROXY_VERSION", "${CLIPROXY_VERSION}"),
            # «Мониторинг» показывает время развёртывания (раздел 15.5).
            ("DEPLOYED_AT", "${DEPLOYED_AT:-}"),
        ],
    )
    def test_backend_environment(
        self,
        compose: dict[str, Any],
        variable: str,
        value: str,
    ) -> None:
        assert compose["services"]["backend"]["environment"][variable] == value

    def test_tokens_only_in_proxy(self, compose: dict[str, Any]) -> None:
        """
        Раздел 19.4: volume с токенами OAuth — только у прокси и его init, и
        для чтения у воркера бэкапа (раздел 20.4: копия шифруется).
        """
        owners = {
            name
            for name, service in compose["services"].items()
            if "cliproxy_data" in _volume_names(service)
        }
        assert owners == {"cliproxy", "cliproxy-init", "backup-worker"}

    def test_proxy_waits_for_config(self, compose: dict[str, Any]) -> None:
        depends = compose["services"]["cliproxy"]["depends_on"]
        assert depends == {"cliproxy-init": {"condition": "service_completed_successfully"}}


class TestSessionNetwork:
    def test_network_named(self, compose: dict[str, Any]) -> None:
        # Выход наружу нужен MCP-серверам: другой сети у контейнера сессии нет.
        assert compose["networks"]["llm_sessions"] == {"name": _SESSION_NETWORK}

    def test_only_gateway_on_session_network(self, compose: dict[str, Any]) -> None:
        on_network = {
            name
            for name, service in compose["services"].items()
            if "llm_sessions" in service.get("networks", [])
        }
        assert on_network == {"llm-gateway"}

    @pytest.mark.parametrize("service", ["worker", "session-worker"])
    def test_worker_attaches_sessions(self, compose: dict[str, Any], service: str) -> None:
        worker = compose["services"][service]
        assert worker["environment"]["TRACKER_SESSION_LLM_NETWORK"] == _SESSION_NETWORK
        assert "claude_sessions" in _volume_names(worker)

    def test_gateway_has_no_docker_socket(self, compose: dict[str, Any]) -> None:
        gateway = compose["services"]["llm-gateway"]
        assert "/var/run/docker.sock" not in _volume_names(gateway)
        assert "CLIPROXY_MANAGEMENT_KEY" not in gateway["environment"]


def _render(tmp_path: Path, **keys: str) -> subprocess.CompletedProcess[str]:
    script = (_CLIPROXY_DIR / "init.sh").read_text()
    script = script.replace("/opt/cliproxy/", f"{_CLIPROXY_DIR}/").replace(
        "DATA_DIR=/data",
        f"DATA_DIR={tmp_path}",
    )
    return subprocess.run(
        ["sh", "-c", script],
        env={"PATH": "/usr/bin:/bin", **keys},
        capture_output=True,
        text=True,
        check=False,
    )


class TestCliproxyInit:
    def test_renders_keys(self, tmp_path: Path) -> None:
        result = _render(tmp_path, CLIPROXY_API_KEY="a1b2", CLIPROXY_MANAGEMENT_KEY="c3d4")

        assert result.returncode == 0, result.stderr
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert config["access"]["api-keys"] == ["a1b2"]
        assert config["management"]["secret-key"] == "c3d4"
        assert config["routing"]["force-model-prefix"] is True
        assert config["management"]["disable-control-panel"] is True
        assert config["observability"]["logs"]["request-log"] is False
        assert config["oauth"]["auth-dir"] == "/data/auths"

    def test_rerender_replaces_config(self, tmp_path: Path) -> None:
        _render(tmp_path, CLIPROXY_API_KEY="old1", CLIPROXY_MANAGEMENT_KEY="old2")

        _render(tmp_path, CLIPROXY_API_KEY="new1", CLIPROXY_MANAGEMENT_KEY="new2")

        assert "old" not in (tmp_path / "config.yaml").read_text()

    @pytest.mark.parametrize(
        "keys",
        [
            {"CLIPROXY_MANAGEMENT_KEY": "c3d4"},
            {"CLIPROXY_API_KEY": "", "CLIPROXY_MANAGEMENT_KEY": "c3d4"},
            {"CLIPROXY_API_KEY": "a/b", "CLIPROXY_MANAGEMENT_KEY": "c3d4"},
        ],
        ids=["missing", "empty", "unsafe"],
    )
    def test_rejects_bad_keys(self, tmp_path: Path, keys: dict[str, str]) -> None:
        result = _render(tmp_path, **keys)

        assert result.returncode == 1
        assert not (tmp_path / "config.yaml").exists()

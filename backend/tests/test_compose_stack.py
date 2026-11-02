"""
Стек docker-compose: LLM-прокси, шлюз и сеть сессий (разделы 19.3, 19.4,
19.7, 20.3 ТЗ) и рендер конфигурации прокси `deploy/cliproxy/init.sh`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

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


class TestLlmProxy:
    def test_proxy_not_published(self, compose: dict[str, Any]) -> None:
        assert "ports" not in compose["services"]["cliproxy"]

    def test_proxy_built_from_pinned_tag(self, compose: dict[str, Any]) -> None:
        context = compose["services"]["cliproxy"]["build"]["context"]
        assert context == "https://github.com/router-for-me/CLIProxyAPI.git#${CLIPROXY_VERSION}"

    def test_tokens_only_in_proxy(self, compose: dict[str, Any]) -> None:
        """Раздел 19.4: volume с токенами OAuth — только у прокси и его init."""
        owners = {
            name
            for name, service in compose["services"].items()
            if "cliproxy_data" in _volume_names(service)
        }
        assert owners == {"cliproxy", "cliproxy-init"}

    def test_proxy_waits_for_config(self, compose: dict[str, Any]) -> None:
        depends = compose["services"]["cliproxy"]["depends_on"]
        assert depends == {"cliproxy-init": {"condition": "service_completed_successfully"}}


class TestSessionNetwork:
    def test_network_internal_and_named(self, compose: dict[str, Any]) -> None:
        assert compose["networks"]["llm_sessions"] == {"name": _SESSION_NETWORK, "internal": True}

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

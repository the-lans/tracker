"""Необязательное подключение kubectl и kubeconfig к LLM-сессиям."""

import pytest

from services.session_container import kubernetes_args


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACKER_SESSION_KUBERNETES_DIR", raising=False)
    assert kubernetes_args() == []


def test_credentials_mounted_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACKER_SESSION_KUBERNETES_DIR", "/etc/tracker/kubernetes")
    args = kubernetes_args()
    assert args == [
        "--mount",
        "type=bind,src=/etc/tracker/kubernetes/kubectl,dst=/usr/local/bin/kubectl,readonly",
        "--mount",
        "type=bind,src=/etc/tracker/kubernetes/config,dst=/opt/tracker-kubernetes/config,readonly",
        "-e",
        "KUBECONFIG=/opt/tracker-kubernetes/config",
    ]


def test_relative_path_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACKER_SESSION_KUBERNETES_DIR", "relative/path")
    with pytest.raises(ValueError, match="абсолютным"):
        kubernetes_args()

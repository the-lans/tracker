"""
Заголовки безопасности Caddy (раздел 20.3): конфигурация разбирается самим
Caddy (`caddy adapt` в его образе), заголовки стоят на всех ответах сайта,
HSTS настраивается `HSTS_MAX_AGE`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

_CADDYFILE = Path(__file__).resolve().parents[2] / "deploy" / "caddy" / "Caddyfile"
_CADDY_IMAGE = "caddy:2-alpine"
_DOMAIN = "tracker.example.com"
# Источники, без которых не работают вход Google и шрифты.
_REQUIRED_CSP_PARTS = (
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com/gsi/client",
    "frame-src https://accounts.google.com/gsi/",
    "font-src 'self' https://fonts.gstatic.com",
    "frame-ancestors 'none'",
    "object-src 'none'",
)


def _response_headers(env: dict[str, str]) -> dict[str, Any]:
    args = [arg for name, value in env.items() for arg in ("-e", f"{name}={value}")]
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            *args,
            "-v",
            f"{_CADDYFILE}:/etc/caddy/Caddyfile:ro",
            _CADDY_IMAGE,
            "caddy",
            "adapt",
            "--config",
            "/etc/caddy/Caddyfile",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    site = json.loads(result.stdout)["apps"]["http"]["servers"]["srv0"]["routes"][0]
    first = site["handle"][0]["routes"][0]["handle"][0]
    assert first["handler"] == "headers"
    response: dict[str, Any] = first["response"]
    return response


class TestSecurityHeaders:
    def test_headers_on_every_response(self) -> None:
        response = _response_headers({"DOMAIN": _DOMAIN})
        headers = response["set"]

        csp = headers["Content-Security-Policy"][0]
        assert all(part in csp for part in _REQUIRED_CSP_PARTS), csp
        assert "'unsafe-eval'" not in csp
        assert "script-src 'self' 'unsafe-inline'" not in csp
        assert headers["X-Content-Type-Options"] == ["nosniff"]
        assert headers["X-Frame-Options"] == ["DENY"]
        assert response["delete"] == ["Server"]

    @pytest.mark.parametrize(
        ("env", "expected"),
        [({}, "max-age=31536000"), ({"HSTS_MAX_AGE": "0"}, "max-age=0")],
        ids=["default", "stand"],
    )
    def test_hsts_max_age(self, env: dict[str, str], expected: str) -> None:
        headers = _response_headers({"DOMAIN": _DOMAIN, **env})["set"]

        assert headers["Strict-Transport-Security"] == [expected]

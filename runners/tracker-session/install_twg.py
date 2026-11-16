"""Установка закреплённого официального TWG и его навыков при сборке образа."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path


def main() -> None:
    lock = json.loads(Path(__file__).with_name("twg.lock.json").read_text())
    machine = platform.machine()
    architecture = {"aarch64": "arm64", "x86_64": "x64"}[machine]
    url = f"{lock['source']}/twg-linux-{architecture}-v{lock['version']}"
    binary = Path("/usr/local/bin/twg")
    with (
        urllib.request.urlopen(url, timeout=120) as response,
        binary.open("wb") as target,
    ):
        shutil.copyfileobj(response, target)
    with binary.open("rb") as candidate:
        digest = hashlib.file_digest(candidate, "sha256").hexdigest()
    if digest != lock["sha256"][machine]:
        binary.unlink()
        raise RuntimeError("Контрольная сумма TWG не совпала с twg.lock.json")
    binary.chmod(0o755)
    plugin = Path("/opt/tracker-twg")
    config = Path("/opt/tracker-twg-runtime")
    plugin.mkdir()
    subprocess.run(
        [str(binary), "skills", "install", "--local", "--agent", "claude", "--yes"],
        cwd=plugin,
        env={**os.environ, "TWG_CONFIG_DIR": str(config)},
        check=True,
    )
    skills = config / "skills"
    installed = {
        p.name: json.loads((p / ".twg-install.json").read_text())["contentRevision"]
        for p in skills.iterdir()
        if p.is_dir()
    }
    if installed != lock["skills"]:
        raise RuntimeError(
            "Состав навыков TWG изменился: проверьте и обновите lock-файл"
        )
    (plugin / "skills").symlink_to(skills)
    metadata = plugin / ".claude-plugin"
    metadata.mkdir()
    (metadata / "plugin.json").write_text(
        json.dumps(
            {
                "name": "twg",
                "version": lock["version"],
                "description": "Навыки Atlassian Teamwork Graph для сессий Tracker",
            },
            ensure_ascii=False,
        )
    )
    for root in (config, plugin):
        root.chmod(0o755)
        for path in root.rglob("*"):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == "__main__":
    main()

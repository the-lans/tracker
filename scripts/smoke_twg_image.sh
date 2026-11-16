#!/usr/bin/env bash
set -euo pipefail
SESSION_IMAGE="${1:-tracker-session:latest}"

# Без авторизации, сети, модели и доступа к данным пользователя.
docker run --rm -i --network none --user 10001:10001 --tmpfs /tmp -e HOME=/tmp \
  "$SESSION_IMAGE" python - <<'PY'
import json
import os
import subprocess
from pathlib import Path

lock = json.loads(Path('/opt/tracker-twg-installer/twg.lock.json').read_text())
assert subprocess.check_output(['twg', '--version'], text=True).strip() == lock['version']
plugin = Path('/opt/tracker-twg')
assert json.loads((plugin / '.claude-plugin/plugin.json').read_text())['name'] == 'twg'
for name in lock['skills']:
    skill = plugin / 'skills' / name
    assert (skill / 'SKILL.md').read_text().startswith('---')
    assert (skill / 'LICENSE.txt').is_file()
    assert not os.access(skill / 'SKILL.md', os.W_OK)
plugins = json.loads(subprocess.check_output(
    ['claude', '--plugin-dir', str(plugin), 'plugin', 'list', '--json'], text=True,
))
assert any(p['enabled'] and p['installPath'] == str(plugin) for p in plugins)
subprocess.run(['twg', 'help', 'describe', 'jira workitem get', '--output-summary', 'none'],
               check=True, stdout=subprocess.DEVNULL)
print('TWG: версия, навыки, права доступа и справка проверены без сети.')
PY

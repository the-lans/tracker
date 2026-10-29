"""Нода «Тесты» пайплайна «QA: фича с тестами» (docs/qa_e2e_manual.md)."""

import os
import subprocess
import sys

if os.path.exists(os.path.join(os.environ["TASK_ARTIFACTS_PATH"], "fail-tests")):
    print("fail-tests найден в артефактах — сбой по сценарию QA")
    sys.exit(1)

repo = os.path.join(os.environ["TASK_REPOS_PATH"], "qa-calc")
result = subprocess.run(
    [sys.executable, "-m", "unittest", "-v"],
    cwd=repo,
    capture_output=True,
    text=True,
)
print(result.stdout + result.stderr)
sys.exit(result.returncode)

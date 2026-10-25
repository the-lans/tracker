# Нода «Сбор контекста» пайплайна «QA: фича с тестами» (docs/qa_e2e_manual.md).
set -euo pipefail
cd "$TASK_REPOS_PATH/qa-calc"
echo "Файлы:"; ls -1
echo "README:"; cat README.md
echo "Проверка сети:"; (getent hosts example.com && echo "СЕТЬ ЕСТЬ") || echo "сети нет"
ls -1 > "$TASK_ARTIFACTS_PATH/qa-context.txt"

#!/usr/bin/env bash
# Стенд ручного E2E-тестирования (docs/qa_e2e_manual.md) рядом с запущенным
# `docker compose up -d`: git-хост по SSH с репозиторием qa-calc и мок Jira/GitLab
# в сети compose — worker видит их как qa-git и qa-mocks.
#
#   scripts/qa/stand.sh env                — создать .env трекера из scripts/qa/qa.env
#   scripts/qa/stand.sh seed               — первый администратор и периодические задачи
#   scripts/qa/stand.sh up                 — поднять стенд (повторный запуск безопасен)
#   scripts/qa/stand.sh merge <ветка>      — слить ветку в main и отметить MR как merged
#   scripts/qa/stand.sh export             — копия репозитория в .qa/qa-calc.git для проверки
#   scripts/qa/stand.sh down               — удалить контейнеры и данные стенда
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
QA_DIR="$ROOT_DIR/.qa"
QA_ENV="$ROOT_DIR/scripts/qa/qa.env"
# Настройки стенда (шаблон — scripts/qa/qa.env.example); переменные окружения
# вызова имеют приоритет над файлом.
if [[ -f "$QA_ENV" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ -n "${!key:-}" ]] || export "$key=$value"
  done < "$QA_ENV"
fi
NETWORK="${QA_NETWORK:-tracker_default}"
GIT_IMAGE="tracker-qa-git:latest"
GIT_CONTAINER="qa-git"
GIT_VOLUME="qa-git-data"
MOCKS_CONTAINER="qa-mocks"
MOCKS_PORT="${QA_MOCKS_PORT:-8090}"
REPO_PATH="/srv/git/qa/qa-calc.git"
GIT_URL="ssh://git@${GIT_CONTAINER}${REPO_PATH}"

as_git() {
  docker exec -u git "$GIT_CONTAINER" sh -c "$1"
}

git_identity='git -c user.name="QA Stand" -c user.email=qa@example.com'

require_qa_env() {
  [[ -f "$QA_ENV" ]] || {
    echo "Нет $QA_ENV: cp scripts/qa/qa.env.example scripts/qa/qa.env и заполните" >&2
    exit 1
  }
}

# Значение подставляется как есть: строка KEY=... в .env заменяется целиком.
set_env_value() {
  local key="$1" value="$2" file="$ROOT_DIR/.env"
  KEY="$key" VALUE="$value" awk -F= -v OFS='=' \
    '$1 == ENVIRON["KEY"] { print ENVIRON["KEY"], ENVIRON["VALUE"]; next } { print }' \
    "$file" > "$file.tmp"
  mv "$file.tmp" "$file"
}

make_env() {
  require_qa_env
  [[ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" && -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ]] || {
    echo "Заполните GOOGLE_OAUTH_CLIENT_ID и GOOGLE_OAUTH_CLIENT_SECRET в $QA_ENV" >&2
    exit 1
  }
  [[ ! -f "$ROOT_DIR/.env" ]] || {
    echo ".env уже есть — не перезаписываю (удалите его, чтобы создать заново)" >&2
    exit 1
  }
  (umask 077 && cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env")
  set_env_value DOMAIN localhost
  set_env_value ACME_EMAIL "$QA_ADMIN_EMAIL"
  set_env_value GOOGLE_OAUTH_CLIENT_ID "$GOOGLE_OAUTH_CLIENT_ID"
  set_env_value GOOGLE_OAUTH_CLIENT_SECRET "$GOOGLE_OAUTH_CLIENT_SECRET"
  local key
  for key in SECRET_ENCRYPTION_KEY SESSION_SECRET_KEY POSTGRES_PASSWORD REDIS_PASSWORD SFTP_DB_PASSWORD; do
    set_env_value "$key" "$(openssl rand -hex 32)"
  done
  chmod 600 "$ROOT_DIR/.env"
  echo ".env создан: DOMAIN=localhost, секреты сгенерированы. Дальше: docker compose up -d"
}

seed() {
  require_qa_env
  (cd "$ROOT_DIR" \
    && docker compose run --rm backend python /app/scripts/seed_admin_allowlist.py "$QA_ADMIN_EMAIL" \
    && docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py)
  echo "Администратор: $QA_ADMIN_EMAIL. Вход в Claude для LLM-аккаунта:"
  echo "  docker compose exec -e CLAUDE_CONFIG_DIR=$QA_CLAUDE_ACCOUNT_DIR worker claude auth login"
}

up() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || {
    echo "Сеть $NETWORK не найдена: сначала docker compose up -d (или задайте QA_NETWORK)" >&2
    exit 1
  }
  mkdir -p "$QA_DIR/keys"
  [[ -f "$QA_DIR/deploy_key" ]] || ssh-keygen -q -t ed25519 -N "" -C "qa-deploy@example.com" -f "$QA_DIR/deploy_key"
  cp "$QA_DIR/deploy_key.pub" "$QA_DIR/keys/deploy_key.pub"

  docker build -q -t "$GIT_IMAGE" "$ROOT_DIR/scripts/qa/git-server" >/dev/null
  docker rm -f "$GIT_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$GIT_CONTAINER" --network "$NETWORK" \
    -v "$QA_DIR/keys:/keys:ro" -v "$GIT_VOLUME:/srv/git" "$GIT_IMAGE" >/dev/null
  docker exec "$GIT_CONTAINER" chown git:git /srv/git

  if ! as_git "test -d $REPO_PATH"; then
    docker exec "$GIT_CONTAINER" rm -rf /tmp/seed
    docker cp "$ROOT_DIR/scripts/qa/seed/qa-calc" "$GIT_CONTAINER:/tmp/seed"
    docker exec "$GIT_CONTAINER" chown -R git:git /tmp/seed
    as_git "mkdir -p $(dirname "$REPO_PATH") && git init -q --bare -b main $REPO_PATH \
      && cd /tmp/seed && git init -q -b main && git add . \
      && $git_identity commit -q -m 'chore: initial calculator' \
      && git push -q $REPO_PATH main && rm -rf /tmp/seed/.git"
  fi

  docker rm -f "$MOCKS_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$MOCKS_CONTAINER" --network "$NETWORK" \
    -p "127.0.0.1:${MOCKS_PORT}:8090" \
    -v "$ROOT_DIR/scripts/qa:/qa:ro" python:3.12-slim \
    python /qa/mock_providers.py --port 8090 >/dev/null

  cat <<EOF
Стенд готов.
  Адрес репозитория (раздел «Репозитории»): $GIT_URL
  Deploy key (вставить приватный ключ):     $QA_DIR/deploy_key
  Jira URL и GitLab URL («Системные настройки»): http://${MOCKS_CONTAINER}:8090
  Журнал обращений к мокам: curl -s http://localhost:${MOCKS_PORT}/_qa/requests
EOF
}

merge() {
  local branch="${1:?укажите ветку, например feature/RR-QA-1}"
  as_git "rm -rf /tmp/merge && git clone -q $REPO_PATH /tmp/merge && cd /tmp/merge \
    && $git_identity merge -q --no-ff origin/$branch -m 'Merge $branch' \
    && git push -q origin main && rm -rf /tmp/merge"
  curl -sf -X POST "http://localhost:${MOCKS_PORT}/_qa/merge-requests" \
    -H 'Content-Type: application/json' \
    -d "{\"source_branch\": \"$branch\", \"state\": \"merged\"}"
  echo
}

export_repo() {
  rm -rf "$QA_DIR/qa-calc.git"
  docker cp "$GIT_CONTAINER:$REPO_PATH" "$QA_DIR/qa-calc.git"
  echo "Копия: $QA_DIR/qa-calc.git — git clone -b <ветка> $QA_DIR/qa-calc.git $QA_DIR/check"
}

down() {
  docker rm -f "$GIT_CONTAINER" "$MOCKS_CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$GIT_VOLUME" >/dev/null 2>&1 || true
  rm -rf "$QA_DIR"
  echo "Стенд удалён."
}

case "${1:-}" in
  env) make_env ;;
  seed) seed ;;
  up) up ;;
  merge) merge "${2:-}" ;;
  export) export_repo ;;
  down) down ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac

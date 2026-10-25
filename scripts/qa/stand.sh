#!/usr/bin/env bash
# Стенд ручного E2E-тестирования (docs/qa_e2e_manual.md): .env трекера,
# git-хост по SSH с репозиторием qa-calc и мок Jira/GitLab в сети compose
# (worker видит их как qa-git и qa-mocks), тестовые данные.
#
#   scripts/qa/stand.sh env            — .env и frontend/.env трекера из scripts/qa/qa.env
#                                        (повторный запуск дописывает новое, секреты сохраняет)
#   scripts/qa/stand.sh seed           — первый администратор и периодические задачи
#   scripts/qa/stand.sh up             — поднять git-хост и мок (повторный запуск безопасен)
#   scripts/qa/stand.sh data           — тестовые справочники и эталонный пайплайн
#   scripts/qa/stand.sh trust          — корневой сертификат Caddy для доверия браузера
#   scripts/qa/stand.sh merge <ветка>  — слить ветку в main и отметить MR как merged
#   scripts/qa/stand.sh export         — копия репозитория в .qa/qa-calc.git для проверки
#   scripts/qa/stand.sh down           — удалить git-хост, мок и .qa/ (.env не трогает)
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
COMPOSE_PROJECT="${QA_COMPOSE_PROJECT:-tracker-qa}"
NETWORK="${QA_NETWORK:-${COMPOSE_PROJECT}_default}"
GIT_IMAGE="tracker-qa-git:latest"
GIT_CONTAINER="qa-git"
GIT_VOLUME="qa-git-data"
MOCKS_CONTAINER="qa-mocks"
MOCKS_PORT="${QA_MOCKS_PORT:-8090}"
REPO_PATH="/srv/git/qa/qa-calc.git"
GIT_URL="ssh://git@${GIT_CONTAINER}${REPO_PATH}"
TRACKER_ENV="$ROOT_DIR/.env"
FRONTEND_ENV="$ROOT_DIR/frontend/.env"
GENERATED_SECRETS=(SECRET_ENCRYPTION_KEY SESSION_SECRET_KEY POSTGRES_PASSWORD REDIS_PASSWORD SFTP_DB_PASSWORD)

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

# Значение подставляется как есть: строка KEY=... заменяется целиком.
set_env_value() {
  local file="$1" key="$2" value="$3"
  KEY="$key" VALUE="$value" awk -F= -v OFS='=' \
    '$1 == ENVIRON["KEY"] { print ENVIRON["KEY"], ENVIRON["VALUE"]; next } { print }' \
    "$file" > "$file.tmp"
  cat "$file.tmp" > "$file" && rm -f "$file.tmp"
}

# Как set_env_value, но добавляет строку, если ключа в файле нет.
ensure_env_value() {
  local file="$1" key="$2" value="$3"
  if grep -q "^$key=" "$file"; then
    set_env_value "$file" "$key" "$value"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

env_value() {
  sed -n "s/^$2=//p" "$1" | head -n 1
}

# Раздел 18.1: VAPID — пара ключей P-256, как в deploy/install.sh: публичный
# ключ в urlsafe-base64 для PushManager.subscribe, приватный — сырые 32 байта.
generate_vapid() {
  local vapid_dir
  vapid_dir="$(mktemp -d)"
  docker run --rm -v "${vapid_dir}:/vapid" -w /vapid python:3.12-slim sh -c '
    pip install --quiet --disable-pip-version-check --root-user-action=ignore py-vapid==1.9.4 cryptography==50.0.2
    vapid --gen --applicationServerKey > gen_output.txt
    python3 - <<"PY"
from cryptography.hazmat.primitives import serialization
import base64
with open("private_key.pem", "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None)
raw = key.private_numbers().private_value.to_bytes(32, "big")
with open("private_key.raw.txt", "w") as f:
    f.write(base64.urlsafe_b64encode(raw).rstrip(b"=").decode())
PY
  ' >/dev/null
  set_env_value "$TRACKER_ENV" VAPID_PUBLIC_KEY \
    "$(sed -n 's/^Application Server Key = //p' "${vapid_dir}/gen_output.txt")"
  set_env_value "$TRACKER_ENV" VAPID_PRIVATE_KEY "$(cat "${vapid_dir}/private_key.raw.txt")"
  rm -rf "${vapid_dir}"
  echo "  VAPID-ключи сгенерированы"
}

make_env() {
  require_qa_env
  if [[ ! -f "$TRACKER_ENV" ]]; then
    (umask 077 && cp "$ROOT_DIR/.env.example" "$TRACKER_ENV")
    echo ".env создан из .env.example"
  fi
  chmod 600 "$TRACKER_ENV"
  # Свой compose-проект: volume и сеть стенда не пересекаются с другим стеком трекера.
  ensure_env_value "$TRACKER_ENV" COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT"
  set_env_value "$TRACKER_ENV" DOMAIN localhost
  set_env_value "$TRACKER_ENV" ACME_EMAIL "$QA_ADMIN_EMAIL"
  set_env_value "$TRACKER_ENV" VAPID_CLAIMS_EMAIL "$QA_ADMIN_EMAIL"
  # Сгенерированные секреты не перегенерируются: ключ шифрования и пароли
  # уже использованы данными в volume.
  local key
  for key in "${GENERATED_SECRETS[@]}"; do
    [[ -n "$(env_value "$TRACKER_ENV" "$key")" ]] || set_env_value "$TRACKER_ENV" "$key" "$(openssl rand -hex 32)"
  done
  [[ -n "$(env_value "$TRACKER_ENV" VAPID_PRIVATE_KEY)" ]] || generate_vapid

  [[ -f "$FRONTEND_ENV" ]] || cp "$ROOT_DIR/frontend/.env.example" "$FRONTEND_ENV"
  if [[ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" && -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ]]; then
    set_env_value "$TRACKER_ENV" GOOGLE_OAUTH_CLIENT_ID "$GOOGLE_OAUTH_CLIENT_ID"
    set_env_value "$TRACKER_ENV" GOOGLE_OAUTH_CLIENT_SECRET "$GOOGLE_OAUTH_CLIENT_SECRET"
    # Client ID встраивается в бандл при сборке образа frontend.
    set_env_value "$FRONTEND_ENV" VITE_GOOGLE_CLIENT_ID "$GOOGLE_OAUTH_CLIENT_ID"
    echo ".env и frontend/.env готовы. Применить: docker compose up -d --build"
  else
    echo "GOOGLE_OAUTH_* в $QA_ENV не заполнены — вход через Google пока недоступен." >&2
    echo "Заполните их и повторите: scripts/qa/stand.sh env && docker compose up -d --build" >&2
  fi
}

seed() {
  require_qa_env
  (cd "$ROOT_DIR" \
    && docker compose run --rm backend python /app/scripts/seed_admin_allowlist.py "$QA_ADMIN_EMAIL" \
    && docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py)
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
  docker run -d --name "$GIT_CONTAINER" --network "$NETWORK" --restart unless-stopped \
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
  docker run -d --name "$MOCKS_CONTAINER" --network "$NETWORK" --restart unless-stopped \
    -p "127.0.0.1:${MOCKS_PORT}:8090" \
    -v "$ROOT_DIR/scripts/qa:/qa:ro" python:3.12-slim \
    python /qa/mock_providers.py --port 8090 >/dev/null

  cat <<EOF
Git-хост и мок запущены.
  Репозиторий: $GIT_URL (deploy key — $QA_DIR/deploy_key)
  Jira и GitLab: http://${MOCKS_CONTAINER}:8090
  Журнал обращений к мокам: curl -s http://localhost:${MOCKS_PORT}/_qa/requests
Тестовые данные: scripts/qa/stand.sh data
EOF
}

data() {
  require_qa_env
  [[ -f "$QA_DIR/deploy_key" ]] || { echo "Сначала scripts/qa/stand.sh up" >&2; exit 1; }
  (cd "$ROOT_DIR" && docker compose run --rm --no-deps \
    -v "$ROOT_DIR/scripts/qa:/app/scripts/qa:ro" \
    -v "$QA_DIR/deploy_key:/run/qa/deploy_key:ro" \
    backend python /app/scripts/qa/seed_qa_data.py \
    --admin-email "$QA_ADMIN_EMAIL" \
    --claude-config-dir "$QA_CLAUDE_ACCOUNT_DIR" \
    --deploy-key /run/qa/deploy_key)
  cat <<EOF
Тестовые данные готовы. Вход в Claude для LLM-аккаунта «QA»:
  docker compose exec -e CLAUDE_CONFIG_DIR=$QA_CLAUDE_ACCOUNT_DIR worker claude auth login
EOF
}

trust() {
  mkdir -p "$QA_DIR"
  (cd "$ROOT_DIR" && docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$QA_DIR/caddy-root.crt")
  cat <<EOF
Корневой сертификат Caddy: $QA_DIR/caddy-root.crt
Без доверия к нему браузер не регистрирует service worker — Web Push не работает.
  macOS: sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$QA_DIR/caddy-root.crt"
  Linux: sudo cp "$QA_DIR/caddy-root.crt" /usr/local/share/ca-certificates/caddy-qa.crt && sudo update-ca-certificates
Затем перезапустите браузер.
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
  echo "Git-хост, мок и .qa/ удалены. Стек трекера: docker compose down"
}

case "${1:-}" in
  env) make_env ;;
  seed) seed ;;
  up) up ;;
  data) data ;;
  trust) trust ;;
  merge) merge "${2:-}" ;;
  export) export_repo ;;
  down) down ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac

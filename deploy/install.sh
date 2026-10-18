#!/usr/bin/env bash
# Единственный скрипт установки трекера на новый сервер, запускаемый вручную
# администратором (раздел 20.2, 20.3 ТЗ).

set -euo pipefail

REPO_URL="https://github.com/the-lans/tracker.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/tracker}"
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"
# Заполняется step_prompt_critical_values, читается step_seed_data (раздел
# 19.1 — курица и яйцо, см. scripts/seed_admin_allowlist.py).
ADMIN_EMAIL=""

log() { echo "[install.sh] $*"; }

# Шаг 1: проверка и установка Docker + Docker Compose plugin
step_install_docker() {
  log "Шаг 1/11: проверка Docker и Docker Compose plugin"
  if ! command -v docker >/dev/null 2>&1; then
    log "Docker не найден."
    # TODO: установить Docker Engine по официальной инструкции для текущего
    # дистрибутива (get.docker.com или пакетный менеджер) и завершить установку.
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "Docker Compose plugin не найден."
    # TODO: установить docker-compose-plugin.
    exit 1
  fi
}

# Шаг 2: клонирование репозитория в целевую директорию
step_clone_repo() {
  log "Шаг 2/11: клонирование репозитория в ${INSTALL_DIR}"
  if [ -d "${INSTALL_DIR}/.git" ]; then
    log "Репозиторий уже присутствует в ${INSTALL_DIR}, пропуск клонирования"
  else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi
}

# Подставляет значение ключа KEY в ${ENV_FILE} (KEY= уже присутствует в
# .env.example — sed только заполняет пустое значение, не добавляет строку).
_set_env_value() {
  local key="$1" value="$2"
  # '|' как разделитель sed — секреты могут содержать '/' (base64).
  sed -i.bak "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  rm -f "${ENV_FILE}.bak"
}

# Шаг 3: генерация .env из .env.example — все секреты через openssl rand
step_generate_env() {
  log "Шаг 3/11: генерация ${ENV_FILE} из ${ENV_EXAMPLE}"
  if [ -f "${ENV_FILE}" ]; then
    log "${ENV_FILE} уже существует, пропуск генерации"
    return
  fi
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"

  _set_env_value SECRET_ENCRYPTION_KEY "$(openssl rand -hex 32)"
  _set_env_value SESSION_SECRET_KEY "$(openssl rand -hex 32)"
  _set_env_value POSTGRES_PASSWORD "$(openssl rand -base64 24)"
  _set_env_value REDIS_PASSWORD "$(openssl rand -base64 24)"

  # Раздел 18.1: VAPID-ключевая пара для Web Push — не openssl rand, а
  # валидная EC-ключевая пара (P-256, пакет py-vapid, зависимость backend
  # через pywebpush), которую браузер обязан суметь разобрать через
  # `PushManager.subscribe({applicationServerKey: <публичный ключ>})`.
  # Генерируется одноразовым контейнером (py-vapid — зависимость backend'а,
  # не хоста, а сам backend-образ на этом шаге ещё не собран, см. шаг 5) —
  # `--applicationServerKey` печатает публичный ключ в urlsafe-base64,
  # именно в этом виде фронтенд передаёт его в `PushManager.subscribe`.
  local vapid_dir
  vapid_dir="$(mktemp -d)"
  # `pywebpush.webpush(vapid_private_key=...)`, когда получает НЕ путь к
  # файлу (наш случай — значение переменной окружения, не путь), передаёт
  # строку в `py_vapid.Vapid02.from_string`, которая ожидает "сырой"
  # 32-байтный приватный ключ в urlsafe-base64 БЕЗ PEM-обрамления
  # ("-----BEGIN EC PRIVATE KEY-----..." не является валидным base64) —
  # поэтому приватный ключ извлекается из .pem через `cryptography`, а не
  # просто "убрать переносы строк" из файла.
  docker run --rm -v "${vapid_dir}:/vapid" -w /vapid python:3.12-slim sh -c '
    pip install --quiet py-vapid==1.9.4 cryptography==50.0.1
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
  '
  _set_env_value VAPID_PUBLIC_KEY \
    "$(grep "Application Server Key" "${vapid_dir}/gen_output.txt" | sed 's/^Application Server Key = //')"
  _set_env_value VAPID_PRIVATE_KEY "$(cat "${vapid_dir}/private_key.raw.txt")"
  rm -rf "${vapid_dir}"
}

# Шаг 4: интерактивный запрос критичных значений
step_prompt_critical_values() {
  log "Шаг 4/11: запрос домена, email для TLS, Google OAuth Client ID/Secret, email администратора"
  local domain acme_email oauth_client_id oauth_client_secret
  read -rp "Домен (например, tracker.example.com): " domain
  read -rp "Email для выпуска TLS-сертификата (Let's Encrypt): " acme_email
  read -rp "Google OAuth Client ID: " oauth_client_id
  read -rsp "Google OAuth Client Secret: " oauth_client_secret
  echo
  # Раздел 19.1: НОВАЯ регистрация (включая самую первую) требует, чтобы
  # email уже был в allowed_emails — без этого шага войти в систему не
  # сможет вообще никто (см. scripts/seed_admin_allowlist.py, вызывается
  # из step_seed_data после применения миграций).
  read -rp "Email первого администратора (тот же Google-аккаунт, которым будете входить): " ADMIN_EMAIL
  _set_env_value DOMAIN "${domain}"
  _set_env_value ACME_EMAIL "${acme_email}"
  _set_env_value GOOGLE_OAUTH_CLIENT_ID "${oauth_client_id}"
  _set_env_value GOOGLE_OAUTH_CLIENT_SECRET "${oauth_client_secret}"
  # VAPID_CLAIMS_EMAIL (раздел 18.1) — тот же email подходит для VAPID-claim'а.
  _set_env_value VAPID_CLAIMS_EMAIL "${acme_email}"
}

# Шаг 5: сборка Docker-образов
step_build_images() {
  log "Шаг 5/11: сборка образов backend, frontend, раннеров script-нод"
  ( cd "${INSTALL_DIR}" && docker compose build backend frontend )
  # Раннеры не входят в docker-compose.yml — запускаются on-demand Celery
  # worker'ом через docker.sock (раздел 11.4, 19.3), а не как долгоживущий
  # сервис; имена образов обязаны совпадать с
  # `services/nodes/script.py::DEFAULT_RUNNER_IMAGES`.
  docker build -t tracker-runner-python:latest "${INSTALL_DIR}/runners/tracker-runner-python"
  docker build -t tracker-runner-bash:latest "${INSTALL_DIR}/runners/tracker-runner-bash"
}

# Шаг 6: поднятие инфраструктурных сервисов первыми, с healthcheck
step_start_infra() {
  log "Шаг 6/11: запуск PostgreSQL и Redis"
  ( cd "${INSTALL_DIR}" && docker compose up -d --wait postgres redis )
}

# Шаг 7: применение миграций БД
step_run_migrations() {
  log "Шаг 7/11: применение миграций Alembic"
  # Миграции применяются автоматически в entrypoint backend-образа
  # (backend/docker-entrypoint.sh, идемпотентно) при каждом старте backend/
  # worker/beat — явный вызов здесь избыточен, но остаётся как ручной
  # fallback, дающий понятную ошибку до старта прикладных сервисов, если
  # миграции почему-то не применились.
  ( cd "${INSTALL_DIR}" && docker compose run --rm backend alembic upgrade head )
}

# Шаг 8: заполнение начальных данных (seed)
step_seed_data() {
  log "Шаг 8/11: заполнение seed-данных (allowed_emails, periodic_tasks)"
  # Раздел 19.1: без этого email администратора не сможет войти вообще —
  # см. scripts/seed_admin_allowlist.py и комментарий в step_prompt_critical_values.
  ( cd "${INSTALL_DIR}" \
    && docker compose run --rm backend python /app/scripts/seed_admin_allowlist.py "${ADMIN_EMAIL}" )

  # periodic_tasks (раздел 16.2), в отличие от allowed_emails, требует уже
  # СУЩЕСТВУЮЩЕГО пользователя-администратора (updated_by — FK на users) —
  # первый вход через Google OAuth ещё не выполнен на этом шаге ни разу,
  # поэтому этот под-шаг откладывается: администратор перезапускает
  # команду вручную после первого входа (см. шаг 11/step_final_instructions).
  ( cd "${INSTALL_DIR}" \
    && docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py ) \
    || log "Seed periodic_tasks пропущен — повторите вручную после первого входа администратора: docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py"
}

# Шаг 9: старт прикладных сервисов
step_start_app_services() {
  log "Шаг 9/11: запуск backend, worker, beat, frontend, caddy, backup"
  ( cd "${INSTALL_DIR}" && docker compose up -d backend worker beat frontend caddy backup )
}

# Шаг 10: получение TLS-сертификата — выполняется автоматически Caddy
step_wait_tls() {
  log "Шаг 10/11: Caddy автоматически получит TLS-сертификат для указанного домена"
}

# Шаг 11: первый вход администратора
step_final_instructions() {
  log "Шаг 11/11: откройте https://<DOMAIN> и войдите через Google OAuth (${ADMIN_EMAIL}) — первый пользователь автоматически получит роль admin"
  log "После первого входа выполните: cd ${INSTALL_DIR} && docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py"
}

main() {
  step_install_docker
  step_clone_repo
  step_generate_env
  step_prompt_critical_values
  step_build_images
  step_start_infra
  step_run_migrations
  step_seed_data
  step_start_app_services
  step_wait_tls
  step_final_instructions
  log "Установка завершена"
}

main "$@"

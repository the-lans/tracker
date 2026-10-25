#!/usr/bin/env bash
# Единственный скрипт установки трекера на новый сервер, запускаемый вручную
# администратором (раздел 20.2, 20.3 ТЗ).
#
#   deploy/install.sh                     — новая установка
#   deploy/install.sh --restore <каталог> — перенос на новый сервер (раздел
#     20.4, docs/migration.md): в каталоге .env, дамп БД *.sql.gz,
#     task_repos.tar.gz, user_files.tar.gz, log_archive.tar.gz, claude_accounts.tar.gz
#     и sftp_host_keys.tar.gz со старого сервера
#   deploy/install.sh --update            — обновление установленного сервера
#     до свежего кода (раздел 20.6): пересборка всех образов, в том числе
#     раннеров и tracker-session, миграции и перезапуск сервисов

set -euo pipefail

REPO_URL="https://github.com/the-lans/tracker.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/tracker}"
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"
DOCKER_INSTALL_SCRIPT_URL="https://get.docker.com"
# Раздел 20.2 п. 1: script-ноды монтируют подпуть volume (`volume-subpath`,
# services/nodes/script.py) — он появился в Docker Engine 26.
MIN_DOCKER_ENGINE_MAJOR=26
# Заполняется step_prompt_critical_values, читается step_seed_data (раздел
# 19.1 — курица и яйцо, см. scripts/seed_admin_allowlist.py).
ADMIN_EMAIL=""
# Каталог с архивами переноса; пусто — обычная установка.
RESTORE_DIR=""
RESTORE_DUMP=""
# --update: обновление уже установленного сервера.
UPDATE_MODE=""
# Архив -> точка монтирования volume[ -> сервис, по умолчанию backend]
# (docker-compose.yml).
RESTORE_ARCHIVES=(
  "task_repos:/data/repos"
  "user_files:/data/user-files"
  "log_archive:/data/log-archive"
)
# Необязательные: на сервере прежней версии такого volume ещё не было.
RESTORE_OPTIONAL_ARCHIVES=(
  "claude_accounts:/data/claude-accounts"
  # У backend этот volume только для чтения — распаковывает сам шлюз.
  "sftp_host_keys:/data/sftp-host-keys:sftp"
)

log() { echo "[install.sh] $*"; }

die() {
  log "Ошибка: $*"
  exit 1
}

usage() {
  echo "Использование: $0 [--restore <каталог с .env, *.sql.gz, task_repos.tar.gz, user_files.tar.gz, log_archive.tar.gz, claude_accounts.tar.gz> | --update]"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --restore)
        [ "$#" -ge 2 ] || { usage; exit 2; }
        RESTORE_DIR="$2"
        shift 2
        ;;
      --update)
        UPDATE_MODE="1"
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        log "Неизвестный аргумент: $1"
        usage
        exit 2
        ;;
    esac
  done
  if [ -n "${RESTORE_DIR}" ] && [ -n "${UPDATE_MODE}" ]; then
    log "--restore и --update несовместимы"
    usage
    exit 2
  fi
}

# Команда от root: скрипт обычно запускают от root, иначе — через sudo.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

_install_compose_plugin() {
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y docker-compose-plugin
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y docker-compose-plugin
  elif command -v yum >/dev/null 2>&1; then
    as_root yum install -y docker-compose-plugin
  else
    die "не найден пакетный менеджер для установки docker-compose-plugin"
  fi
}

# Шаг 1: проверка и установка Docker + Docker Compose plugin
step_install_docker() {
  log "Шаг 1/11: проверка Docker и Docker Compose plugin"
  if ! command -v docker >/dev/null 2>&1; then
    # Официальный скрипт Docker ставит Engine вместе с плагином Compose
    # для поддерживаемых дистрибутивов.
    log "Docker не найден — установка через ${DOCKER_INSTALL_SCRIPT_URL}"
    local installer
    installer="$(mktemp)"
    curl -fsSL "${DOCKER_INSTALL_SCRIPT_URL}" -o "${installer}"
    as_root sh "${installer}"
    rm -f "${installer}"
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "Docker Compose plugin не найден — установка пакета docker-compose-plugin"
    _install_compose_plugin
  fi
  docker compose version >/dev/null 2>&1 || die "Docker Compose plugin так и не стал доступен"
  _check_docker_engine_version
}

_check_docker_engine_version() {
  local version major
  version="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" \
    || die "Docker Engine недоступен: не удалось узнать версию (запущен ли демон Docker?)"
  major="${version%%.*}"
  case "${major}" in
    '' | *[!0-9]*) die "Не удалось разобрать версию Docker Engine: '${version}'" ;;
  esac
  if [ "${major}" -lt "${MIN_DOCKER_ENGINE_MAJOR}" ]; then
    die "Нужен Docker Engine ${MIN_DOCKER_ENGINE_MAJOR} или новее, установлен ${version} — обновите Docker"
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

# Задаёт значение, только если его ещё нет: .env прежней версии (перенос)
# может не знать о новых переменных.
_ensure_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=." "${ENV_FILE}"; then
    return
  fi
  if grep -q "^${key}=" "${ENV_FILE}"; then
    _set_env_value "${key}" "${value}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
  log "В ${ENV_FILE} добавлено значение ${key}"
}

# Раздел 20.5: пароль роли БД SFTP-шлюза входит в DATABASE_URL — только hex.
_generate_sftp_db_password() {
  openssl rand -hex 24
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
  _set_env_value SFTP_DB_PASSWORD "$(_generate_sftp_db_password)"

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
  log "Шаг 5/11: сборка образов backend, frontend, раннеров script-нод и сессии"
  ( cd "${INSTALL_DIR}" && docker compose build backend frontend )
  # Раннеры не входят в docker-compose.yml — запускаются on-demand Celery
  # worker'ом через docker.sock (раздел 11.4, 19.3), а не как долгоживущий
  # сервис; имена образов обязаны совпадать с
  # `services/nodes/script.py::DEFAULT_RUNNER_IMAGES`.
  docker build -t tracker-runner-python:latest "${INSTALL_DIR}/runners/tracker-runner-python"
  docker build -t tracker-runner-bash:latest "${INSTALL_DIR}/runners/tracker-runner-bash"
  # Контейнер сессии — процесс Claude Code CLI задачи (раздел 19.3); имя —
  # `services/session_container.py::DEFAULT_SESSION_IMAGE`.
  docker build -t tracker-session:latest "${INSTALL_DIR}/runners/tracker-session"
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

  _seed_periodic_tasks
}

# periodic_tasks (раздел 16.2): записи создаются системой (updated_by =
# NULL, раздел 3.1), администратор для этого не нужен; повторный запуск
# идемпотентен и добавляет только новые задачи.
_seed_periodic_tasks() {
  ( cd "${INSTALL_DIR}" \
    && docker compose run --rm backend python /app/scripts/seed_periodic_tasks.py )
}

# Шаг 9: старт прикладных сервисов
step_start_app_services() {
  log "Шаг 9/11: запуск backend, worker, session-worker, beat, sftp, frontend, caddy, backup"
  ( cd "${INSTALL_DIR}" && docker compose up -d backend worker session-worker beat sftp frontend caddy backup )
}

# Шаг 10: получение TLS-сертификата — выполняется автоматически Caddy
step_wait_tls() {
  log "Шаг 10/11: Caddy автоматически получит TLS-сертификат для указанного домена"
}

# Шаг 11: первый вход администратора
step_final_instructions() {
  log "Шаг 11/11: откройте https://<DOMAIN> и войдите через Google OAuth (${ADMIN_EMAIL}) — первый пользователь автоматически получит роль admin"
  # Раздел 19.5: вход в Claude выполняется в каталоге уже заведённого LLM-аккаунта.
  # Раздел 15.1, 20.3: доступ к файлам задач по SFTP/sshfs.
  log "SFTP-шлюз слушает порт SFTP_PORT из ${ENV_FILE} (по умолчанию 2222) — откройте его в файрволе; инструкция подключения — в профиле трекера"
  log "Вход в Claude для LLM-аккаунта (после того как пользователь завёл его в разделе «LLM-аккаунты»): cd ${INSTALL_DIR} && docker compose exec -e CLAUDE_CONFIG_DIR=<каталог аккаунта> worker claude auth login"
}

# --- Восстановление на новом сервере (раздел 20.4, docs/migration.md) ---

# До установки чего-либо: перенос без полного набора файлов бессмысленен.
validate_restore_dir() {
  [ -d "${RESTORE_DIR}" ] || die "каталог восстановления ${RESTORE_DIR} не найден"
  RESTORE_DIR="$(cd "${RESTORE_DIR}" && pwd)"
  [ -f "${RESTORE_DIR}/.env" ] || die "в ${RESTORE_DIR} нет .env со старого сервера"
  local mapping archive
  for mapping in "${RESTORE_ARCHIVES[@]}"; do
    archive="${mapping%%:*}.tar.gz"
    [ -f "${RESTORE_DIR}/${archive}" ] || die "в ${RESTORE_DIR} нет ${archive}"
  done
  # Имена дампов встроенного бэкапа содержат UTC-таймстамп — последний по
  # имени и есть самый свежий.
  RESTORE_DUMP="$(find "${RESTORE_DIR}" -maxdepth 1 -name '*.sql.gz' | sort | tail -n 1)"
  [ -n "${RESTORE_DUMP}" ] || die "в ${RESTORE_DIR} нет дампа БД *.sql.gz"
}

# Ключи шифрования обязаны совпадать со старым сервером — иначе секреты в
# БД не расшифруются (раздел 3.2, 19.4).
step_restore_env() {
  log "Восстановление: перенос .env"
  if [ -f "${ENV_FILE}" ]; then
    cp "${ENV_FILE}" "${ENV_FILE}.before-restore"
    log "Прежний ${ENV_FILE} сохранён как ${ENV_FILE}.before-restore"
  fi
  cp "${RESTORE_DIR}/.env" "${ENV_FILE}"
  _ensure_env_value SFTP_DB_PASSWORD "$(_generate_sftp_db_password)"
}

# В пустую БД и до миграций: дамп содержит схему старого сервера, миграции
# затем лишь доводят её до текущей версии кода.
step_restore_database() {
  log "Восстановление: дамп БД $(basename "${RESTORE_DUMP}")"
  gzip -dc "${RESTORE_DUMP}" | (cd "${INSTALL_DIR}" \
    && docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
}

# Тома монтирует сам сервис — имя compose-проекта знать не нужно.
step_restore_volumes() {
  local mapping archive target service rest
  for mapping in "${RESTORE_ARCHIVES[@]}" "${RESTORE_OPTIONAL_ARCHIVES[@]}"; do
    archive="${mapping%%:*}.tar.gz"
    rest="${mapping#*:}"
    target="${rest%%:*}"
    service="backend"
    if [ "${rest}" != "${target}" ]; then
      service="${rest#*:}"
    fi
    if [ ! -f "${RESTORE_DIR}/${archive}" ]; then
      log "Восстановление: ${archive} нет в переносе — пропуск"
      continue
    fi
    log "Восстановление: ${archive} -> ${target}"
    (cd "${INSTALL_DIR}" && docker compose run --rm --no-deps \
      -v "${RESTORE_DIR}:/restore:ro" --entrypoint sh "${service}" \
      -c "find '${target}' -mindepth 1 -delete && tar xzf '/restore/${archive}' -C '${target}'")
  done
}

run_install() {
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

# Seed не нужен: пользователи, allowlist и periodic_tasks уже в дампе.
run_restore() {
  step_restore_env
  step_build_images
  step_start_infra
  step_restore_database
  step_restore_volumes
  step_run_migrations
  step_start_app_services
  step_wait_tls
  log "Восстановление завершено: откройте https://<DOMAIN> и войдите прежним аккаунтом администратора"
}

# --- Обновление установленного сервера (раздел 20.6) ---

validate_update() {
  [ -d "${INSTALL_DIR}/.git" ] || die "в ${INSTALL_DIR} нет установленного трекера — сначала обычная установка"
  [ -f "${ENV_FILE}" ] || die "нет ${ENV_FILE} — сначала обычная установка"
}

step_pull_repo() {
  log "Обновление: получение свежего кода в ${INSTALL_DIR}"
  # Только перемотка вперёд: локальные правки на сервере не затираются молча.
  git -C "${INSTALL_DIR}" pull --ff-only
}

# Образы раннеров и tracker-session не входят в docker-compose.yml — без
# пересборки здесь сессии и script-ноды остались бы на старых образах или
# не нашли бы новый (раздел 19.3).
run_update() {
  step_pull_repo
  _ensure_env_value SFTP_DB_PASSWORD "$(_generate_sftp_db_password)"
  step_build_images
  step_start_infra
  step_run_migrations
  _seed_periodic_tasks
  step_start_app_services
  log "Обновление завершено"
}

main() {
  parse_args "$@"
  if [ -n "${RESTORE_DIR}" ]; then
    validate_restore_dir
  fi
  if [ -n "${UPDATE_MODE}" ]; then
    validate_update
  fi
  step_install_docker
  if [ -n "${UPDATE_MODE}" ]; then
    run_update
    return
  fi
  step_clone_repo
  if [ -n "${RESTORE_DIR}" ]; then
    run_restore
  else
    run_install
  fi
}

# Функции можно подключить через `source` (тест скрипта) без запуска установки.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi

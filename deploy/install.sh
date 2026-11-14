#!/usr/bin/env bash
# Единственный скрипт установки трекера на новый сервер, запускаемый вручную
# администратором (раздел 20.2, 20.3 ТЗ).
#
#   deploy/install.sh                     — новая установка
#   deploy/install.sh --restore <каталог> — перенос на новый сервер (раздел
#     20.4, docs/migration.md): в каталоге .env, дамп БД *.sql.gz,
#     task_repos.tar.gz, user_files.tar.gz, log_archive.tar.gz и необязательные
#     claude_sessions.tar.gz, cliproxy_data.tar.gz, sftp_host_keys.tar.gz со
#     старого сервера (и claude_accounts.tar.gz копии прежней версии); --ref <коммит> — версия кода,
#     на которой сняты архивы (restore.sh копии в S3 передаёт коммит из
#     manifest.json), без него — вершина origin/main
#   deploy/install.sh --update [--ref <коммит>] [--wait-idle <минуты>] —
#     обновление установленного сервера (раздел 20.6): флаг обслуживания,
#     ожидание живых сессий, переход на коммит из origin/main, пересборка
#     всех образов (в том числе раннеров и tracker-session), дамп БД,
#     миграции, перенос истории сессий, перезапуск сервисов и удаление
#     висячих образов трекера

set -euo pipefail

REPO_URL="https://github.com/the-lans/tracker.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/tracker}"
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"
DOCKER_INSTALL_SCRIPT_URL="https://get.docker.com"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
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
# --ref: коммит из истории origin/main вместо её вершины (в том числе откат);
# при --restore — версия кода, на которой снята копия.
UPDATE_REF=""
# --wait-idle: сколько минут ждать завершения живых сессий.
WAIT_IDLE_MINUTES=""
WAIT_IDLE_POLL_SECONDS="${WAIT_IDLE_POLL_SECONDS:-15}"
# Статусы задач с живой сессией (services/task_status.py::SESSION_ACTIVE_STATUSES).
LIVE_SESSION_STATUSES="'in_progress','paused','plan_review','awaiting_input','rebase_conflict'"
# Раздел 20.6: статусы до запуска, которых не знает версия без этой миграции.
PRE_LAUNCH_STATUSES_MIGRATION="alembic/versions/a3f9d2c71e58_task_queue_statuses.py"
PRE_LAUNCH_STATUSES_ADDED="'refining','defined','ready','night_worker'"
# Раздел 20.6: статус awaiting_limit, которого не знает версия без этой
# миграции. Ждущие лимита задачи возвращаются в её статусы — тем же запросом,
# что downgrade миграции (_RESTORE_LIMIT_WAITS).
LIMIT_WAIT_MIGRATION="alembic/versions/e5b81c4d2f97_llm_limit_control.py"
# Новые причины смены аккаунта в node_logs — ближайшими прежними
# (_RESTORE_SWITCH_REASONS миграции): иначе прежняя версия не прочитает ленту.
LIMIT_SWITCH_REASONS_RESET="UPDATE node_logs SET llm_switch_reason = CASE llm_switch_reason::text WHEN 'week_exhausted' THEN 'threshold_week'::llm_switch_reason ELSE 'threshold_5h'::llm_switch_reason END WHERE llm_switch_reason::text IN ('window_planned', 'window_balance', 'week_exhausted')"
LIMIT_WAIT_RESET="UPDATE tasks SET status = CASE WHEN limit_wait_from_status::text = 'refining' THEN 'refining'::task_status ELSE 'failed'::task_status END, last_failed_order_index = CASE WHEN limit_wait_from_status::text = 'refining' THEN last_failed_order_index ELSE coalesce(limit_wait_order_index, last_failed_order_index) END WHERE status::text = 'awaiting_limit'"
# Периодические задачи воркера очереди: прежняя версия их не знает. Новая
# создаёт их заново сидом (scripts/seed_periodic_tasks.py).
QUEUE_PERIODIC_TASKS="'dispatch_ready_tasks','dispatch_night_tasks'"
# Раздел 20.6: ссылки нод пайплайна на библиотеку и переменная
# {{node.guide_url}}, которых не знает версия без этой миграции. Нода получает
# копию содержимого элемента, переменная — гайд ноды; тем же запросом, что
# downgrade миграции (_RESTORE_LIBRARY_CONTENT, _RESTORE_GUIDE_URL).
LIBRARY_LINKS_MIGRATION="alembic/versions/c4e7a2b9d518_events_and_library_links.py"
LIBRARY_CONTENT_RESET="UPDATE nodes SET prompt_template = library_items.prompt_template, command_invocation = library_items.command_invocation, script_language = library_items.script_language, script_content = library_items.script_content, docker_image = library_items.docker_image, guide_url = library_items.guide_url FROM nodes AS library_items WHERE nodes.library_node_id = library_items.id"
# Периодическая задача замера места на диске: прежний worker её не знает.
MONITORING_PERIODIC_TASKS="'measure_volume_usage'"
# Раздел 20.6: статус archived, которого не знает версия без этой миграции.
# Архивная задача возвращается в итоговый статус тем же запросом, что
# downgrade миграции (_RESTORE_ARCHIVED); периодических задач архивации и
# очистки прежний worker не знает.
ARCHIVE_MIGRATION="alembic/versions/f3a8c5e1d927_task_archive.py"
ARCHIVE_RESET="UPDATE tasks SET status = archived_from_status WHERE status::text = 'archived'"
ARCHIVE_PERIODIC_TASKS="'archive_finished_tasks','cleanup_finished_task_repositories'"
# Раздел 20.6: периодические задачи сроков хранения данных, которых прежний
# worker не знает.
RETENTION_MIGRATION="alembic/versions/b7d4e2a9c615_data_retention.py"
RETENTION_PERIODIC_TASKS="'cleanup_archived_task_sessions','cleanup_archived_task_artifacts','purge_old_app_logs'"
# Раздел 20.6: синхронизация Google Calendar «Дейли», которой прежний worker не знает.
DAILY_MIGRATION="alembic/versions/e5c9a3d7f142_daily_plans.py"
DAILY_PERIODIC_TASKS="'sync_google_calendars'"
GUIDE_URL_RESET="UPDATE nodes SET prompt_template = regexp_replace(prompt_template, '[{][{][[:space:]]*node[.]guide_url[[:space:]]*[}][}]', coalesce(guide_url, ''), 'g') WHERE prompt_template LIKE '%node.guide_url%'"
# Флаг обслуживания (services/maintenance.py::MAINTENANCE_KEY): запуск задач
# отвечает 503, воркер не берёт задачи из queued. TTL — срок ожидания плюс
# запас на сборку и миграции: упавший скрипт не оставит флаг навсегда.
MAINTENANCE_KEY="maintenance:deploy"
MAINTENANCE_TTL_MARGIN_SECONDS=3600
MAINTENANCE_SET=""
# .deploy/previous_ref — коммит до обновления, цель отката (раздел 20.7).
DEPLOY_STATE_DIR="${INSTALL_DIR}/.deploy"
# Роль SFTP-шлюза: права на неё есть в дампе прежнего сервера, а создаёт её
# entrypoint backend (sftp_gateway/db_role.py) только при старте — после
# загрузки дампа. Пустая роль без входа заранее; вход и пароль ей задаст
# entrypoint.
SFTP_DB_ROLE_SQL='DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '"'"'tracker_sftp'"'"') THEN CREATE ROLE tracker_sftp NOLOGIN; END IF; END $$;'
# Выполняется после дампа, если есть в копии (services/backup/bundle.py).
AFTER_RESTORE_SQL="after-restore.sql"
# Архив -> точка монтирования volume[ -> сервис, по умолчанию backend]
# (docker-compose.yml).
RESTORE_ARCHIVES=(
  "task_repos:/data/repos"
  "user_files:/data/user-files"
  "log_archive:/data/log-archive"
)
# Необязательные: на сервере прежней версии такого volume ещё не было.
RESTORE_OPTIONAL_ARCHIVES=(
  "claude_sessions:/data/claude-sessions"
  # Учётки прокси с токенами OAuth; volume подключён только к прокси.
  "cliproxy_data:/data:cliproxy-init"
  # У backend этот volume только для чтения — распаковывает сам шлюз.
  "sftp_host_keys:/data/sftp-host-keys:sftp"
)

# Каталоги LLM-аккаунтов прежних версий — источник переноса истории сессий
# (раздел 20.6). Новые копии их не содержат; архив старой копии
# распаковывается во временный том, после переноса том удаляется.
LEGACY_ACCOUNTS_VOLUME_KEY="claude_accounts"
LEGACY_ACCOUNTS_MOUNT="/data/claude-accounts"
# Раздел 20.6: после обновления удаляются только висячие образы трекера (без
# -a: образ, на котором есть контейнер, Docker не удаляет — сессия и
# script-нода на прежнем образе его сохраняют) и кеш сборки старше недели.
RUNNER_IMAGE_LABEL="tracker.image=runner"
BUILD_CACHE_KEEP="168h"

log() { echo "[install.sh] $*"; }

die() {
  log "Ошибка: $*"
  exit 1
}

# --update прерван до перехода на новый код: сервер не изменён, откатывать
# нечего (deploy/ci_deploy.sh и .github/workflows/deploy.yml, раздел 20.7).
EXIT_UNCHANGED=3
# --update после перехода на новый коммит продолжается его версией скрипта:
# процесс получает этот флаг и пропускает уже выполненные шаги.
UPDATE_RESUME_FLAG="TRACKER_UPDATE_FETCHED"
SCRIPT_ARGS=()

die_unchanged() {
  log "Ошибка: $* — сервер не изменён"
  exit "${EXIT_UNCHANGED}"
}

usage() {
  echo "Использование: $0 [--restore <каталог с .env, *.sql.gz и архивами volume> [--ref <коммит>] | --update [--ref <коммит>] [--wait-idle <минуты>]]"
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
      --ref)
        [ "$#" -ge 2 ] || { usage; exit 2; }
        UPDATE_REF="$2"
        shift 2
        ;;
      --wait-idle)
        [ "$#" -ge 2 ] || { usage; exit 2; }
        WAIT_IDLE_MINUTES="$2"
        shift 2
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
  _validate_update_options
}

_validate_update_options() {
  if [ -z "${UPDATE_MODE}" ] && [ -n "${WAIT_IDLE_MINUTES}" ]; then
    log "--wait-idle применяется только с --update"
    usage
    exit 2
  fi
  if [ -z "${UPDATE_MODE}" ] && [ -z "${RESTORE_DIR}" ] && [ -n "${UPDATE_REF}" ]; then
    log "--ref применяется только с --update или --restore"
    usage
    exit 2
  fi
  # Коммит попадает в командную строку git — только шестнадцатеричный SHA.
  if [ -n "${UPDATE_REF}" ] && ! [[ "${UPDATE_REF}" =~ ^[0-9a-f]{7,40}$ ]]; then
    log "--ref ожидает SHA коммита, получено: ${UPDATE_REF}"
    exit 2
  fi
  if [ -n "${WAIT_IDLE_MINUTES}" ] && ! [[ "${WAIT_IDLE_MINUTES}" =~ ^[0-9]+$ ]]; then
    log "--wait-idle ожидает число минут, получено: ${WAIT_IDLE_MINUTES}"
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

step_install_host_dependencies() {
  local tool missing=""
  for tool in git curl openssl; do
    command -v "${tool}" >/dev/null 2>&1 || missing="${missing} ${tool}"
  done
  [ -n "${missing}" ] || return 0
  log "Установка системных зависимостей:${missing}"
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y git curl openssl ca-certificates
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y git curl openssl ca-certificates
  else
    die "установите git, curl, openssl и ca-certificates перед запуском"
  fi
  for tool in git curl openssl; do
    command -v "${tool}" >/dev/null 2>&1 || die "после установки не найдена команда ${tool}"
  done
}

_install_docker_rpm() {
  as_root dnf install -y dnf-plugins-core
  as_root dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  as_root dnf install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  as_root systemctl enable --now docker
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
    local distro
    distro="$(if [ -r "${OS_RELEASE_FILE}" ]; then . "${OS_RELEASE_FILE}"; fi; printf '%s' "${ID:-}")"
    case "${distro}" in
      almalinux|rocky) _install_docker_rpm ;;
      *)
        # get.docker.com не распознаёт AlmaLinux и Rocky Linux.
        log "Docker не найден — установка через ${DOCKER_INSTALL_SCRIPT_URL}"
        local installer
        installer="$(mktemp)"
        curl -fsSL "${DOCKER_INSTALL_SCRIPT_URL}" -o "${installer}"
        as_root sh "${installer}"
        rm -f "${installer}"
        ;;
    esac
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
  [ -n "${value}" ] || die "пустое значение ${key} — запись в .env отменена"
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

# Ставит значение всегда: строка есть — заменяется, нет — дописывается.
_put_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    _set_env_value "${key}" "${value}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
}

_env_file_value() {
  sed -n "s|^$1=||p" "$2" | tail -n 1
}

# Раздел 20.5: пароль роли БД SFTP-шлюза входит в DATABASE_URL — только hex.
_generate_sftp_db_password() {
  openssl rand -hex 24
}

# Раздел 19.4: ключи LLM-прокси; init.sh принимает только буквы и цифры.
_generate_cliproxy_key() {
  openssl rand -hex 32
}

# Перед каждой сборкой, во всех режимах: секреты, которых не знал .env
# прежней версии, версия прокси из репозитория (обновление прокси — смена
# версии в .env.example), коммит сборки для /api/health (раздел 20.7) и
# время развёртывания для страницы «Мониторинг» (раздел 15.5).
step_prepare_env_for_build() {
  _ensure_env_value SFTP_DB_PASSWORD "$(_generate_sftp_db_password)"
  _ensure_env_value CLIPROXY_API_KEY "$(_generate_cliproxy_key)"
  _ensure_env_value CLIPROXY_MANAGEMENT_KEY "$(_generate_cliproxy_key)"
  local cliproxy_version
  cliproxy_version="$(_env_file_value CLIPROXY_VERSION "${ENV_EXAMPLE}")"
  [ -n "${cliproxy_version}" ] || die "в ${ENV_EXAMPLE} не задана CLIPROXY_VERSION"
  _put_env_value CLIPROXY_VERSION "${cliproxy_version}"
  _put_env_value GIT_SHA "$(git -C "${INSTALL_DIR}" rev-parse HEAD)"
  _put_env_value DEPLOYED_AT "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

# Шаг 3: генерация .env из .env.example — все секреты через openssl rand
step_generate_env() {
  log "Шаг 3/11: генерация ${ENV_FILE} из ${ENV_EXAMPLE}"
  if [ -f "${ENV_FILE}" ]; then
    log "${ENV_FILE} уже существует, пропуск генерации"
    return
  fi
  (umask 077; cp "${ENV_EXAMPLE}" "${ENV_FILE}")
  chmod 600 "${ENV_FILE}"

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

step_validate_env() {
  local key value
  for key in DOMAIN ACME_EMAIL GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET \
    SECRET_ENCRYPTION_KEY SESSION_SECRET_KEY POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB \
    REDIS_PASSWORD SFTP_DB_PASSWORD CLIPROXY_API_KEY CLIPROXY_MANAGEMENT_KEY \
    VAPID_PUBLIC_KEY VAPID_PRIVATE_KEY VAPID_CLAIMS_EMAIL; do
    value="$(_env_file_value "${key}" "${ENV_FILE}")"
    case "${value}" in
      ''|'""'|"''") die "в ${ENV_FILE} не задан ${key} — сборка и запуск отменены" ;;
    esac
  done
}

# Шаг 5: сборка Docker-образов
step_build_images() {
  step_validate_env
  log "Шаг 5/11: сборка образов сервисов стека (в том числе LLM-прокси), раннеров script-нод и сессии"
  # Все сервисы с build: у worker, beat, sftp и llm-gateway свои образы из
  # Dockerfile backend — сборка одного backend оставила бы их на старом коде.
  ( cd "${INSTALL_DIR}" && docker compose build )
  # Раннеры не входят в docker-compose.yml — запускаются on-demand Celery
  # worker'ом через docker.sock (раздел 11.4, 19.3), а не как долгоживущий
  # сервис; имена образов обязаны совпадать с
  # `services/nodes/script.py::DEFAULT_RUNNER_IMAGES`.
  docker build --label "${RUNNER_IMAGE_LABEL}" -t tracker-runner-python:latest "${INSTALL_DIR}/runners/tracker-runner-python"
  docker build --label "${RUNNER_IMAGE_LABEL}" -t tracker-runner-bash:latest "${INSTALL_DIR}/runners/tracker-runner-bash"
  # Контейнер сессии — процесс Claude Code CLI задачи (раздел 19.3); имя —
  # `services/session_container.py::DEFAULT_SESSION_IMAGE`.
  docker build --label "${RUNNER_IMAGE_LABEL}" -t tracker-session:latest "${INSTALL_DIR}/runners/tracker-session"
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
  log "Шаг 9/11: запуск cliproxy, llm-gateway, backend, worker, session-worker, backup-worker, beat, sftp, frontend, caddy, backup"
  # cliproxy-init (конфигурация прокси с ключами из .env) запускается как зависимость cliproxy.
  ( cd "${INSTALL_DIR}" \
    && docker compose up -d cliproxy llm-gateway backend worker session-worker backup-worker beat sftp frontend caddy backup )
}

# Шаг 10: получение TLS-сертификата — выполняется автоматически Caddy
step_wait_tls() {
  log "Шаг 10/11: Caddy автоматически получит TLS-сертификат для указанного домена"
}

# Шаг 11: первый вход администратора
step_final_instructions() {
  log "Шаг 11/11: откройте https://<DOMAIN> и войдите через Google OAuth (${ADMIN_EMAIL}) — первый пользователь автоматически получит роль admin"
  # Раздел 15.1, 20.3: доступ к файлам задач по SFTP/sshfs.
  log "SFTP-шлюз слушает порт SFTP_PORT из ${ENV_FILE} (по умолчанию 2222) — откройте его в файрволе; инструкция подключения — в профиле трекера"
  # Раздел 19.5: вход в аккаунт провайдера — через LLM-прокси из интерфейса.
  log "LLM-аккаунты: пользователь заводит аккаунт в разделе «LLM-аккаунты» и входит в провайдера по ссылке из диалога входа — консоль сервера для этого не нужна"
}

# Имя compose-проекта — первая строка `docker compose config` (`name: …`).
_compose_project() {
  { ( cd "${INSTALL_DIR}" && docker compose config 2>/dev/null ) || true; } | sed -n '1s/^name: //p'
}

# Том каталогов прежних LLM-аккаунтов, если он есть: compose его больше не
# объявляет, поэтому ищется по имени `<проект>_claude_accounts`.
_legacy_accounts_volume() {
  local name
  name="$(_compose_project)_${LEGACY_ACCOUNTS_VOLUME_KEY}"
  docker volume ls -q --filter "name=^${name}$" | grep -x "${name}" || true
}

# Перенос истории сессий из каталогов аккаунтов прежней версии (раздел
# 20.6); идемпотентен. Тома нет — переносить нечего. Сбой переноса
# прерывает скрипт: том остаётся и не удаляется.
step_migrate_sessions() {
  local volume
  volume="$(_legacy_accounts_volume)"
  if [ -z "${volume}" ]; then
    log "Каталогов LLM-аккаунтов прежней версии нет — перенос истории сессий не нужен"
    return 0
  fi
  log "Перенос истории сессий задач из тома ${volume} в их каталоги"
  ( cd "${INSTALL_DIR}" \
    && docker compose run --rm -v "${volume}:${LEGACY_ACCOUNTS_MOUNT}:ro" \
      backend python /app/scripts/migrate_claude_sessions.py )
}

# После переноса и перезапуска сервисов: контейнеры пересозданы без этого
# тома. Не удалось (том ещё занят) — повторит следующее обновление.
step_remove_legacy_accounts_volume() {
  local volume
  volume="$(_legacy_accounts_volume)"
  [ -n "${volume}" ] || return 0
  log "Удаление тома ${volume}: история сессий перенесена"
  docker volume rm "${volume}" >/dev/null \
    || log "Предупреждение: том ${volume} не удалён — повтор при следующем обновлении"
}

# Висячие образы трекера и старый кеш сборки (раздел 20.6); сбой не роняет
# уже завершённое обновление.
step_prune_docker() {
  local project
  project="$(_compose_project)"
  log "Обновление: удаление висячих образов трекера и кеша сборки старше ${BUILD_CACHE_KEEP}"
  if [ -n "${project}" ]; then
    docker image prune -f --filter "label=com.docker.compose.project=${project}" >/dev/null \
      || log "Предупреждение: не удалось удалить висячие образы сервисов"
  fi
  docker image prune -f --filter "label=${RUNNER_IMAGE_LABEL}" >/dev/null \
    || log "Предупреждение: не удалось удалить висячие образы раннеров и сессии"
  docker builder prune -f --filter "until=${BUILD_CACHE_KEEP}" >/dev/null \
    || log "Предупреждение: не удалось очистить кеш сборки"
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
}

# Версия кода, на которой снята копия: схема дампа и данные volume — её.
# Коммит должен входить в историю origin/main, как у --update --ref.
step_checkout_restore_ref() {
  [ -n "${UPDATE_REF}" ] || return 0
  local commit
  log "Восстановление: переход на коммит копии ${UPDATE_REF}"
  git -C "${INSTALL_DIR}" fetch origin || die "не удалось получить код из origin"
  commit="$(git -C "${INSTALL_DIR}" rev-parse --verify --quiet "${UPDATE_REF}^{commit}")" \
    || die "коммит ${UPDATE_REF} не найден"
  git -C "${INSTALL_DIR}" merge-base --is-ancestor "${commit}" origin/main \
    || die "коммит ${commit} не входит в историю origin/main"
  git -C "${INSTALL_DIR}" checkout --detach "${commit}" \
    || die "переход на ${commit} мешают локальные правки"
}

# В пустую БД и до миграций: дамп содержит схему старого сервера, миграции
# затем лишь доводят её до текущей версии кода. Копия из S3 несёт
# after-restore.sql — итог запуска бэкапа, во время которого снят дамп.
step_restore_database() {
  log "Восстановление: дамп БД $(basename "${RESTORE_DUMP}")"
  local after_restore="${RESTORE_DIR}/${AFTER_RESTORE_SQL}"
  [ -f "${after_restore}" ] || after_restore=/dev/null
  { echo "${SFTP_DB_ROLE_SQL}"; gzip -dc "${RESTORE_DUMP}"; cat "${after_restore}"; } | (cd "${INSTALL_DIR}" \
    && docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
}

# Архив каталогов аккаунтов из копии прежней версии: том compose больше не
# объявляет — он создаётся под тем же именем, что у прежней версии, и его
# находит перенос истории сессий (step_migrate_sessions).
step_restore_legacy_accounts() {
  local archive="${LEGACY_ACCOUNTS_VOLUME_KEY}.tar.gz" volume
  [ -f "${RESTORE_DIR}/${archive}" ] || return 0
  volume="$(_compose_project)_${LEGACY_ACCOUNTS_VOLUME_KEY}"
  log "Восстановление: ${archive} -> том ${volume} (для переноса истории сессий)"
  docker volume create "${volume}" >/dev/null
  (cd "${INSTALL_DIR}" && docker compose run --rm --no-deps \
    -v "${volume}:${LEGACY_ACCOUNTS_MOUNT}" -v "${RESTORE_DIR}:/restore:ro" --entrypoint sh backend \
    -c "find '${LEGACY_ACCOUNTS_MOUNT}' -mindepth 1 -delete && tar xzf '/restore/${archive}' -C '${LEGACY_ACCOUNTS_MOUNT}'")
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
  step_prepare_env_for_build
  step_build_images
  step_start_infra
  step_run_migrations
  step_seed_data
  step_start_app_services
  step_wait_tls
  step_final_instructions
  log "Установка завершена"
}

# Пользователи и allowlist уже в дампе. Сид периодических задач — как при
# обновлении: дамп прежней версии не знает задач, добавленных позже.
run_restore() {
  step_checkout_restore_ref
  step_restore_env
  step_prepare_env_for_build
  step_build_images
  step_start_infra
  step_restore_database
  step_restore_volumes
  step_restore_legacy_accounts
  step_run_migrations
  _seed_periodic_tasks
  step_migrate_sessions
  step_start_app_services
  step_remove_legacy_accounts_volume
  step_wait_tls
  log "Восстановление завершено: откройте https://<DOMAIN> и войдите прежним аккаунтом администратора"
}

# --- Обновление установленного сервера (раздел 20.6) ---

validate_update() {
  [ -d "${INSTALL_DIR}/.git" ] || die "в ${INSTALL_DIR} нет установленного трекера — сначала обычная установка"
  [ -f "${ENV_FILE}" ] || die "нет ${ENV_FILE} — сначала обычная установка"
}

_redis_cli() {
  # Пароль — через окружение клиента, не в аргументах командной строки.
  ( cd "${INSTALL_DIR}" \
    && REDISCLI_AUTH="$(_env_file_value REDIS_PASSWORD "${ENV_FILE}")" \
      docker compose exec -T -e REDISCLI_AUTH redis redis-cli "$@" )
}

_set_maintenance_flag() {
  local ttl=$(( ${WAIT_IDLE_MINUTES:-0} * 60 + MAINTENANCE_TTL_MARGIN_SECONDS ))
  [ "$(_redis_cli SET "${MAINTENANCE_KEY}" 1 EX "${ttl}")" = "OK" ] \
    || die "не удалось поставить флаг обслуживания в Redis"
  MAINTENANCE_SET="1"
}

# Вызывается и в конце обновления, и по выходу с ошибкой (trap EXIT).
_clear_maintenance_flag() {
  [ -n "${MAINTENANCE_SET}" ] || return 0
  MAINTENANCE_SET=""
  _redis_cli DEL "${MAINTENANCE_KEY}" >/dev/null \
    || log "Флаг обслуживания не снят — он истечёт сам по TTL"
}

_live_session_count() {
  # to_jsonb сохраняет совместимость с версией БД до добавления chat_active.
  local query="SELECT count(*) FROM tasks WHERE status IN (${LIVE_SESSION_STATUSES}) OR to_jsonb(tasks)->>'chat_active' = 'true'"
  ( cd "${INSTALL_DIR}" \
    && docker compose exec -T postgres \
      sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "${query}" )
}

# Сессии, шедшие во время перезапуска, упадут в failed (раздел 6.6) — до
# перезапуска ждём, пока их не останется; новые не стартуют из-за флага.
step_wait_idle() {
  [ -n "${WAIT_IDLE_MINUTES}" ] || return 0
  log "Обновление: ожидание завершения живых сессий (до ${WAIT_IDLE_MINUTES} мин)"
  local deadline count
  deadline=$(( $(date +%s) + WAIT_IDLE_MINUTES * 60 ))
  while true; do
    count="$(_live_session_count)"
    [[ "${count}" =~ ^[0-9]+$ ]] || die_unchanged "не удалось узнать число живых сессий: ${count}"
    [ "${count}" -eq 0 ] && return 0
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      die_unchanged "живые сессии (${count}) не завершились за ${WAIT_IDLE_MINUTES} мин"
    fi
    log "Живых сессий: ${count}, ожидание"
    sleep "${WAIT_IDLE_POLL_SECONDS}"
  done
}

# Откат на версию, которая не знает новых статусов задач (раздел 20.6):
# прежний код не прочитал бы задачу с незнакомым статусом. Ждущие лимита
# задачи уходят в failed (точка перезапуска — нода, которая ждала) или
# обратно в refining; статусы до запуска — в new, а периодические задачи
# воркера очереди, замера диска, сроков хранения данных и синхронизации
# календаря, которых прежний
# worker не знает, удаляются; ноды со ссылкой на библиотеку получают копию её
# промта; архивные задачи возвращаются в done/failed. Одной
# транзакцией, после checkout: если checkout не удался, БД не тронута. Сбой
# здесь возвращает код на прежний коммит — сервер не изменён.
_reset_unknown_task_statuses() {
  local commit="$1" previous="$2" query=""
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${LIMIT_WAIT_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет статуса awaiting_limit — ждущие лимита задачи уходят в failed или refining"
    query="${LIMIT_WAIT_RESET}; ${LIMIT_SWITCH_REASONS_RESET}; "
  fi
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${PRE_LAUNCH_STATUSES_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет статусов до запуска — такие задачи возвращаются в new"
    query+="UPDATE tasks SET status = 'new' WHERE status::text IN (${PRE_LAUNCH_STATUSES_ADDED})"
    query+="; DELETE FROM periodic_tasks WHERE name IN (${QUEUE_PERIODIC_TASKS}); "
  fi
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${LIBRARY_LINKS_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет ссылок на библиотеку и замера диска — ноды получают копию промта, {{node.guide_url}} — гайд ноды"
    query+="${LIBRARY_CONTENT_RESET}; ${GUIDE_URL_RESET}"
    query+="; DELETE FROM periodic_tasks WHERE name IN (${MONITORING_PERIODIC_TASKS}); "
  fi
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${ARCHIVE_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет архива задач — архивные задачи возвращаются в done или failed"
    query+="${ARCHIVE_RESET}; DELETE FROM periodic_tasks WHERE name IN (${ARCHIVE_PERIODIC_TASKS}); "
  fi
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${RETENTION_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет сроков хранения данных — их периодические задачи удаляются"
    query+="DELETE FROM periodic_tasks WHERE name IN (${RETENTION_PERIODIC_TASKS}); "
  fi
  if ! git -C "${INSTALL_DIR}" cat-file -e "${commit}:${DAILY_MIGRATION}" 2>/dev/null; then
    log "Обновление: у версии ${commit} нет «Дейли» — синхронизация Google Calendar удаляется"
    query+="DELETE FROM periodic_tasks WHERE name IN (${DAILY_PERIODIC_TASKS}); "
  fi
  [ -n "${query}" ] || return 0
  ( cd "${INSTALL_DIR}" \
    && docker compose exec -T postgres \
      sh -c 'psql -v ON_ERROR_STOP=1 -1 -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "${query}" ) \
    && return 0
  git -C "${INSTALL_DIR}" checkout --detach "${previous}" \
    || die "не удалось вернуть задачи в статусы прежней версии, а код остался на ${commit}: верните его вручную (git checkout ${previous})"
  die_unchanged "не удалось вернуть задачи в статусы прежней версии перед откатом"
}

# Переход на коммит из истории origin/main: вершина ветки или --ref (в том
# числе откат). Незакоммиченные правки на сервере git не затирает — при
# конфликте checkout прерывает обновление. Прежний коммит — цель отката.
step_fetch_code() {
  local target="${UPDATE_REF:-origin/main}" commit previous
  log "Обновление: получение кода (${target}) в ${INSTALL_DIR}"
  previous="$(git -C "${INSTALL_DIR}" rev-parse HEAD)"
  git -C "${INSTALL_DIR}" fetch origin || die_unchanged "не удалось получить код из origin"
  commit="$(git -C "${INSTALL_DIR}" rev-parse --verify --quiet "${target}^{commit}")" \
    || die_unchanged "коммит ${target} не найден"
  git -C "${INSTALL_DIR}" merge-base --is-ancestor "${commit}" origin/main \
    || die_unchanged "коммит ${commit} не входит в историю origin/main"
  git -C "${INSTALL_DIR}" checkout --detach "${commit}" \
    || die_unchanged "переход на ${commit} мешают локальные правки"
  _reset_unknown_task_statuses "${commit}" "${previous}"
  mkdir -p "${DEPLOY_STATE_DIR}"
  echo "${previous}" > "${DEPLOY_STATE_DIR}/previous_ref"
}

# Перед миграциями: откат возвращает код и образы, а схема остаётся новой —
# дамп позволяет вернуть и данные (раздел 20.6).
step_dump_database() {
  log "Обновление: дамп БД перед миграциями"
  ( cd "${INSTALL_DIR}" && docker compose exec -T backup /usr/local/bin/backup.sh )
}

# Образы раннеров и tracker-session не входят в docker-compose.yml — без
# пересборки здесь сессии и script-ноды остались бы на старых образах или
# не нашли бы новый (раздел 19.3).
# Новые сервисы и шаги версии применяются в том же обновлении, а не со
# следующим. Версия без продолжения (откат на старый коммит) начала бы
# обновление заново и затёрла бы previous_ref — тогда продолжает текущая.
_resume_with_fetched_script() {
  local fetched="${INSTALL_DIR}/deploy/install.sh"
  grep -q "${UPDATE_RESUME_FLAG}" "${fetched}" 2>/dev/null || return 0
  log "Обновление: продолжает install.sh новой версии"
  export "${UPDATE_RESUME_FLAG}=1"
  exec bash "${fetched}" "${SCRIPT_ARGS[@]}"
}

run_update() {
  trap _clear_maintenance_flag EXIT
  if [ -z "${!UPDATE_RESUME_FLAG:-}" ]; then
    step_start_infra
    _set_maintenance_flag
    step_wait_idle
    step_fetch_code
    _resume_with_fetched_script
  fi
  step_prepare_env_for_build
  step_build_images
  step_start_infra
  # Redis мог быть пересоздан новой конфигурацией — флаг ставится заново.
  _set_maintenance_flag
  step_dump_database
  step_run_migrations
  _seed_periodic_tasks
  step_migrate_sessions
  step_start_app_services
  step_remove_legacy_accounts_volume
  step_prune_docker
  _clear_maintenance_flag
  log "Обновление завершено: $(git -C "${INSTALL_DIR}" rev-parse HEAD)"
}

main() {
  SCRIPT_ARGS=("$@")
  parse_args "$@"
  if [ -n "${RESTORE_DIR}" ]; then
    validate_restore_dir
  fi
  if [ -n "${UPDATE_MODE}" ]; then
    validate_update
  fi
  step_install_host_dependencies
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

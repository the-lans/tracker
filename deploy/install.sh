#!/usr/bin/env bash
# Единственный скрипт установки трекера на новый сервер, запускаемый вручную
# администратором (раздел 20.2, 20.3 ТЗ). Заготовка: шаги 3 (генерация
# секретов) и 4 (интерактивный ввод) размечены TODO, остальные шаги содержат
# рабочий минимум команд, достаточный для последовательного прохождения сценария.

set -euo pipefail

REPO_URL="https://github.com/the-lans/tracker.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/tracker}"
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"

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

# Шаг 3: генерация .env из .env.example — все секреты через openssl rand
step_generate_env() {
  log "Шаг 3/11: генерация ${ENV_FILE} из ${ENV_EXAMPLE}"
  if [ -f "${ENV_FILE}" ]; then
    log "${ENV_FILE} уже существует, пропуск генерации"
    return
  fi
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"

  # TODO: сгенерировать секреты и подставить их в ${ENV_FILE} (например, через
  # `sed -i "s/^KEY=.*/KEY=value/"` для каждого ключа):
  #   SECRET_ENCRYPTION_KEY=$(openssl rand -hex 32)
  #   POSTGRES_PASSWORD=$(openssl rand -base64 24)
  #   REDIS_PASSWORD=$(openssl rand -base64 24)
}

# Шаг 4: интерактивный запрос критичных значений
step_prompt_critical_values() {
  log "Шаг 4/11: запрос домена, email для TLS, Google OAuth Client ID/Secret"
  # TODO: запросить значения и подставить их в ${ENV_FILE}, например:
  #   read -rp "Домен: " domain
  #   read -rp "Email для выпуска TLS-сертификата: " acme_email
  #   read -rp "Google OAuth Client ID: " oauth_client_id
  #   read -rsp "Google OAuth Client Secret: " oauth_client_secret
}

# Шаг 5: сборка Docker-образов
step_build_images() {
  log "Шаг 5/11: сборка образов backend, frontend"
  ( cd "${INSTALL_DIR}" && docker compose build backend frontend )
  # TODO: собрать runners/tracker-runner-python и runners/tracker-runner-bash,
  # когда появятся их Dockerfile — эти образы не входят в docker-compose.yml,
  # запускаются on-demand Celery worker'ом через docker.sock.
}

# Шаг 6: поднятие инфраструктурных сервисов первыми, с healthcheck
step_start_infra() {
  log "Шаг 6/11: запуск PostgreSQL и Redis"
  ( cd "${INSTALL_DIR}" && docker compose up -d --wait postgres redis )
}

# Шаг 7: применение миграций БД
step_run_migrations() {
  log "Шаг 7/11: применение миграций Alembic"
  # TODO: в целевой реализации миграции применяются автоматически в entrypoint
  # backend-контейнера (идемпотентно); явный вызов здесь остаётся как ручной
  # fallback на случай отладки развёртывания.
  ( cd "${INSTALL_DIR}" && docker compose run --rm backend alembic upgrade head )
}

# Шаг 8: заполнение начальных данных (seed)
step_seed_data() {
  log "Шаг 8/11: заполнение seed-данных (periodic_tasks, дефолтные Docker-образы раннеров)"
  # TODO: docker compose run --rm backend python -m app.seed, когда появится seed-скрипт.
}

# Шаг 9: старт прикладных сервисов
step_start_app_services() {
  log "Шаг 9/11: запуск backend, worker, beat, frontend, caddy"
  ( cd "${INSTALL_DIR}" && docker compose up -d backend worker beat frontend caddy )
}

# Шаг 10: получение TLS-сертификата — выполняется автоматически Caddy
step_wait_tls() {
  log "Шаг 10/11: Caddy автоматически получит TLS-сертификат для указанного домена"
}

# Шаг 11: первый вход администратора
step_final_instructions() {
  log "Шаг 11/11: откройте https://<DOMAIN> и войдите через Google OAuth — первый пользователь автоматически получит роль admin"
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

#!/usr/bin/env bash
# Регулярная чистка диска сервера (раздел 20.6 ТЗ). Запускается таймером
# systemd `tracker-cleanup.timer` раз в сутки и после каждого обновления
# (`deploy/install.sh`). Каждый шаг необязательный: сбой одного шага не
# останавливает остальные и не считается ошибкой скрипта.
#
# Удаляется только то, что Docker считает неиспользуемым и что можно собрать
# заново: кеш сборки сверх лимита, остановленные контейнеры вне проекта compose
# (брошенные `docker run`, контейнеры проверки копии), безымянные тома без
# контейнеров, а также журнал systemd и кеш пакетов. Контейнеры compose (даже
# остановленные намеренно), именованные тома (`tracker_*`), образы и данные задач
# не затрагиваются: удалённый базовый образ сделал бы сборку зависимой от реестра.

set -uo pipefail

# Кеш сборки сверх этого объёма удаляется, свежие слои остаются.
BUILD_CACHE_MAX_STORAGE="${CLEANUP_BUILD_CACHE_MAX_STORAGE:-4GB}"
STOPPED_CONTAINER_AGE="${CLEANUP_STOPPED_CONTAINER_AGE:-24h}"
JOURNAL_MAX_SIZE="${CLEANUP_JOURNAL_MAX_SIZE:-200M}"
COMPOSE_PROJECT_LABEL="com.docker.compose.project"

log() { echo "[cleanup.sh] $*"; }

# Выполняет команду без вывода; сбой — предупреждение, а не остановка.
best_effort() {
  local description="$1"
  shift
  "$@" >/dev/null 2>&1 || log "Предупреждение: не удалось ${description}"
}

free_space() {
  command -v df >/dev/null 2>&1 || return 0
  df -h / 2>/dev/null | tail -n 1 | tr -s ' ' | cut -d ' ' -f 4
}

clean_docker() {
  command -v docker >/dev/null 2>&1 || { log "docker не найден — чистка Docker пропущена"; return 0; }
  best_effort "ограничить кеш сборки до ${BUILD_CACHE_MAX_STORAGE}" \
    docker builder prune -f --keep-storage "${BUILD_CACHE_MAX_STORAGE}"
  # Контейнеры compose остаются: их остановили осознанно или это разовая задача.
  best_effort "удалить остановленные контейнеры вне compose" \
    docker container prune -f --filter "until=${STOPPED_CONTAINER_AGE}" \
    --filter "label!=${COMPOSE_PROJECT_LABEL}"
  # Без -a удаляются только безымянные тома без контейнеров: именованные
  # (`tracker_*`) и тома существующих контейнеров остаются.
  best_effort "удалить безымянные тома" docker volume prune -f
}

clean_host() {
  # Журнал systemd и кеш пакетов чистит только root: при развёртывании от
  # `deploy` этот шаг делает ночной таймер.
  if [ "$(id -u)" -ne 0 ]; then
    log "Журнал systemd и кеш пакетов пропущены: нужны права root (их чистит таймер)"
    return 0
  fi
  if command -v journalctl >/dev/null 2>&1; then
    best_effort "уменьшить журнал systemd" journalctl "--vacuum-size=${JOURNAL_MAX_SIZE}"
  fi
  if command -v dnf >/dev/null 2>&1; then
    best_effort "очистить кеш dnf" dnf clean packages
  elif command -v apt-get >/dev/null 2>&1; then
    best_effort "очистить кеш apt" apt-get clean
  fi
}

main() {
  local before after
  before="$(free_space)"
  clean_docker
  clean_host
  after="$(free_space)"
  log "Чистка завершена: свободно на / — было ${before:-?}, стало ${after:-?}"
}

# Функции можно подключить через `source` (тест скрипта) без запуска чистки.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi

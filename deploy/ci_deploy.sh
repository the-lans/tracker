#!/usr/bin/env bash
# Принудительная команда ключа развёртывания (раздел 20.7 ТЗ, docs/deployment.md):
#
#   command="<DEPLOY_PATH>/deploy/ci_deploy.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 …
#
# SSH передаёт запрошенную команду в SSH_ORIGINAL_COMMAND; принимаются только
#
#   deploy <sha> [--force | --wait-idle <минуты>]  — install.sh --update --ref <sha>
#   previous-ref                                    — коммит до последнего обновления
#
# SHA — 40 шестнадцатеричных символов. Без флага ожидание живых сессий —
# DEFAULT_WAIT_IDLE_MINUTES; --force — без ожидания. Код выхода install.sh
# передаётся как есть: 3 — обновление отменено, сервер не изменён.

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${DEPLOY_DIR}/install.sh"
export INSTALL_DIR="${DEPLOY_DIR%/deploy}"
PREVIOUS_REF_FILE="${INSTALL_DIR}/.deploy/previous_ref"
DEFAULT_WAIT_IDLE_MINUTES=60
MAX_WAIT_IDLE_MINUTES=1440
EXIT_REJECTED=2

reject() {
  echo "ci_deploy.sh: $*" >&2
  echo "Разрешено: deploy <sha из 40 hex> [--force | --wait-idle <минуты>], previous-ref" >&2
  exit "${EXIT_REJECTED}"
}

_valid_minutes() {
  [[ "$1" =~ ^[0-9]{1,4}$ ]] && [ "$1" -ge 1 ] && [ "$1" -le "${MAX_WAIT_IDLE_MINUTES}" ]
}

run_deploy() {
  local sha="${1:-}"
  [[ "${sha}" =~ ^[0-9a-f]{40}$ ]] || reject "нужен полный SHA коммита"
  shift
  local wait_args=(--wait-idle "${DEFAULT_WAIT_IDLE_MINUTES}")
  case "$#:${1:-}" in
    0:) ;;
    1:--force) wait_args=() ;;
    2:--wait-idle)
      _valid_minutes "$2" || reject "--wait-idle ожидает от 1 до ${MAX_WAIT_IDLE_MINUTES} минут"
      wait_args=(--wait-idle "$2")
      ;;
    *) reject "неизвестные аргументы deploy" ;;
  esac
  # Раскрытие пустого массива — без ошибки set -u и в bash 3.2.
  exec "${INSTALL_SCRIPT}" --update --ref "${sha}" ${wait_args[@]+"${wait_args[@]}"}
}

show_previous_ref() {
  [ "$#" -eq 0 ] || reject "previous-ref без аргументов"
  [ -s "${PREVIOUS_REF_FILE}" ] || { echo "ci_deploy.sh: обновлений ещё не было" >&2; exit 1; }
  cat "${PREVIOUS_REF_FILE}"
}

main() {
  local command="${SSH_ORIGINAL_COMMAND:-}"
  # Одна строка без управляющих символов; слова не раскрываются оболочкой.
  [[ "${command}" =~ ^[[:print:]]+$ ]] || reject "пустая или многострочная команда"
  local words
  read -r -a words <<< "${command}"
  case "${words[0]}" in
    deploy) run_deploy "${words[@]:1}" ;;
    previous-ref) show_previous_ref "${words[@]:1}" ;;
    *) reject "команда не разрешена" ;;
  esac
}

main

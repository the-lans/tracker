#!/usr/bin/env bash
# Восстановление трекера из копии в S3 (раздел 20.4 ТЗ). Подробно — RESTORE.md
# рядом с копией в бакете.
#
#   sudo bash restore.sh <tracker-backup-*.tar.gpg>
#       расшифровать, проверить и восстановить трекер на этом сервере:
#       install.sh --restore на той версии кода, на которой снята копия
#   bash restore.sh <tracker-backup-*.tar.gpg> --extract-only <каталог>
#       только расшифровать, проверить и распаковать (без root и Docker):
#       <каталог>/tracker-backup-*/ — файлы копии, volumes/<имя>/ — данные
#
# Пароль шифрования спросит gpg. Без терминала (скрипт, LLM-агент) — файл с
# паролем в BACKUP_PASSPHRASE_FILE.
# RESTORE_WORK_DIR — куда расшифровать копию (по умолчанию ./tracker-restore).

set -euo pipefail

INSTALL_SCRIPT_URL_TEMPLATE="https://raw.githubusercontent.com/the-lans/tracker/%s/deploy/install.sh"

log() { echo "[restore.sh] $*"; }

die() {
  log "Ошибка: $*"
  exit 1
}

usage() {
  echo "Использование: $0 <tracker-backup-*.tar.gpg> [--extract-only <каталог>]"
}

require_tools() {
  local tool
  for tool in "$@"; do
    command -v "${tool}" >/dev/null 2>&1 || die "нет ${tool} — установите его (RESTORE.md, «Требования»)"
  done
}

sha256_check() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS
  else
    shasum -a 256 -c SHA256SUMS
  fi
}

decrypt() {
  local archive="$1" target="$2"
  local gpg_args=(--decrypt)
  if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
    gpg_args=(--batch --pinentry-mode loopback --passphrase-file "${BACKUP_PASSPHRASE_FILE}" --decrypt)
  fi
  mkdir -p "${target}"
  log "Расшифровка ${archive} в ${target}"
  gpg "${gpg_args[@]}" "${archive}" | tar -xf - -C "${target}"
}

# Коммит трекера, на котором снята копия, из manifest.json.
manifest_commit() {
  sed -n 's/.*"tracker_commit": "\([0-9a-f]\{40\}\)".*/\1/p' "$1/manifest.json" | head -n 1
}

extract_volumes() {
  local bundle="$1" target="$2" archive name
  for archive in "${bundle}"/*.tar.gz; do
    name="$(basename "${archive}" .tar.gz)"
    mkdir -p "${target}/volumes/${name}"
    tar -xzf "${archive}" -C "${target}/volumes/${name}"
    log "Распакован ${name} -> ${target}/volumes/${name}"
  done
}

main() {
  [ "$#" -ge 1 ] || { usage; exit 2; }
  local archive extract_dir="" work_dir bundle commit
  archive="$1"
  shift
  case "${1:-}" in
    "") ;;
    --extract-only)
      [ "$#" -eq 2 ] || { usage; exit 2; }
      extract_dir="$2"
      ;;
    *) usage; exit 2 ;;
  esac
  [ -f "${archive}" ] || die "файл копии ${archive} не найден"
  require_tools gpg tar sed

  work_dir="${extract_dir:-${RESTORE_WORK_DIR:-$(pwd)/tracker-restore}}"
  decrypt "${archive}" "${work_dir}"
  bundle="$(find "${work_dir}" -mindepth 1 -maxdepth 1 -type d -name 'tracker-backup-*' | sort | tail -n 1)"
  [ -n "${bundle}" ] || die "в копии нет каталога tracker-backup-*"
  log "Проверка контрольных сумм"
  (cd "${bundle}" && sha256_check) || die "контрольные суммы не сошлись — копия повреждена"

  if [ -n "${extract_dir}" ]; then
    extract_volumes "${bundle}" "${work_dir}"
    log "Готово: файлы копии — ${bundle}, данные volume — ${work_dir}/volumes"
    return
  fi

  [ "$(id -u)" -eq 0 ] || die "восстановление сервера — от root или через sudo"
  require_tools curl
  commit="$(manifest_commit "${bundle}")"
  local ref_args=()
  if [ -n "${commit}" ]; then
    ref_args=(--ref "${commit}")
  else
    log "В manifest.json нет коммита — восстановление на вершине main"
    commit="main"
  fi
  local installer="${work_dir}/install.sh"
  # shellcheck disable=SC2059
  curl -fsSL "$(printf "${INSTALL_SCRIPT_URL_TEMPLATE}" "${commit}")" -o "${installer}"
  log "Запуск install.sh --restore ${bundle} ${ref_args[*]}"
  bash "${installer}" --restore "${bundle}" "${ref_args[@]}"
}

main "$@"

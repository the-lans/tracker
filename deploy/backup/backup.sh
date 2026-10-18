#!/bin/sh
# Один запуск резервного копирования — вызывается crond по расписанию
# POSTGRES_BACKUP_CRON (раздел 20.4 ТЗ), либо вручную для внепланового
# бэкапа перед переносом на новый сервер (docs/migration.md).
set -eu

BACKUP_DIR="/backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${BACKUP_DIR}/tracker-${STAMP}.sql.gz"

echo "[backup.sh] $(date -u -Iseconds) — старт дампа ${PGDATABASE}@${PGHOST} -> ${DUMP_FILE}"
pg_dump --format=plain | gzip > "${DUMP_FILE}.tmp"
mv "${DUMP_FILE}.tmp" "${DUMP_FILE}"
echo "[backup.sh] дамп готов: $(du -h "${DUMP_FILE}" | cut -f1)"

# Ротация: удаляет дампы старше POSTGRES_BACKUP_RETENTION_DAYS (раздел 20.4).
RETENTION_DAYS="${POSTGRES_BACKUP_RETENTION_DAYS:-14}"
find "${BACKUP_DIR}" -name 'tracker-*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete
echo "[backup.sh] ротация: удалены дампы старше ${RETENTION_DAYS} дней"

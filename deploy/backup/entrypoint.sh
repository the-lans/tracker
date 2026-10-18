#!/bin/sh
# Настраивает расписание crond из POSTGRES_BACKUP_CRON и держит контейнер
# живым (раздел 20.4 ТЗ: "встроенный сервис резервного копирования
# PostgreSQL по расписанию, настраиваемый через .env").
set -eu

mkdir -p /backups

# busybox crond запускает задания с ПУСТЫМ окружением — переменные,
# нужные самому backup.sh (PGHOST/PGUSER/PGPASSWORD/PGDATABASE,
# POSTGRES_BACKUP_RETENTION_DAYS — но НЕ POSTGRES_BACKUP_CRON, он нужен
# только здесь, для строки crontab ниже), нужно захватить сейчас и явно
# подключать в каждом запуске cron-задания. Значения обязательно в
# кавычках — иначе, например, `PGPASSWORD` с пробелом или спецсимволом
# ломает `source` как отдельные слова shell.
env | grep -E '^(PGHOST|PGUSER|PGPASSWORD|PGDATABASE|POSTGRES_BACKUP_RETENTION_DAYS)=' \
  | sed -E 's/^([^=]+)=(.*)$/export \1="\2"/' > /etc/backup_env.sh

# /proc/1/fd/1 — стандартный вывод самого crond (PID 1 контейнера,
# см. `exec crond` ниже) — перенаправление туда делает вывод cron-задания
# видимым в `docker logs`, а не только в файле внутри контейнера.
echo "${POSTGRES_BACKUP_CRON:-0 3 * * *} . /etc/backup_env.sh && /usr/local/bin/backup.sh >>/proc/1/fd/1 2>&1" \
  > /etc/crontabs/root

echo "[entrypoint.sh] расписание: ${POSTGRES_BACKUP_CRON:-0 3 * * *}"
exec crond -f -l 2

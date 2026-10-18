# Встроенный сервис резервного копирования PostgreSQL (раздел 20.4 ТЗ).
# postgres:15-alpine уже содержит pg_dump той же версии, что и сама БД
# (совпадение версий клиента/сервера обязательно для pg_dump), и busybox
# crond (Alpine base) — планировщик по cron-выражению без лишних пакетов.
FROM postgres:15-alpine

COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

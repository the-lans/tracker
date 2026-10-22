#!/usr/bin/env bash
# Раздел 20.2, шаг 7: применение миграций Alembic в entrypoint backend-образа,
# идемпотентно (alembic upgrade head — no-op, если БД уже на актуальной
# версии). Один и тот же образ используется для backend/worker/beat
# (docker-compose.yml) — все три при старте догоняют схему БД до head;
# `depends_on: backend: condition: service_healthy` у worker/beat не даёт им
# стартовать раньше, чем backend впервые применит миграции, так что реальная
# гонка DDL между контейнерами не возникает.
set -euo pipefail

alembic upgrade head
# Раздел 20.5: роль БД SFTP-шлюза — после миграций и при каждом старте
# (pg_dump не переносит роли). Без SFTP_DB_PASSWORD шаг пропускается.
python -m sftp_gateway.db_role

exec "$@"

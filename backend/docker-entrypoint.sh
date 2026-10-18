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

exec "$@"

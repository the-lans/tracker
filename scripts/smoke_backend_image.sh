#!/usr/bin/env bash
# Проверяем runtime без dev-зависимостей: они могут скрыть отсутствующий
# пакет в production-образе (например, packaging для Redis-транспорта Kombu).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="tracker-backend:smoke"
docker build -q -t "${IMAGE}" -f "${ROOT_DIR}/backend/Dockerfile" "${ROOT_DIR}" >/dev/null
docker run --rm --network none --entrypoint python \
  -e REDIS_URL=redis://localhost:6379/0 \
  -e DATABASE_URL=postgresql+asyncpg://tracker:smoke@localhost/tracker \
  -e SECRET_ENCRYPTION_KEY=smoke-only-key \
  -e SESSION_SECRET_KEY=smoke-only-session-key \
  "${IMAGE}" -c '
from kombu.transport.redis import Channel
from main import app
from tasks.celery_app import celery_app

celery_app.loader.import_default_modules()
assert celery_app.connection_for_write().transport_cls == "redis"
print("Production API, worker tasks and Redis transport import successfully")
'

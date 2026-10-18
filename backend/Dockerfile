FROM python:3.12-slim

WORKDIR /app

# Build context — корень репозитория (см. docker-compose.yml:
# `build.context: .`, `build.dockerfile: backend/Dockerfile`), не backend/ —
# нужен доступ к корневому alembic/ (script_location = ../alembic, см.
# backend/alembic.ini) и repo-root scripts/ (seed_periodic_tasks.py,
# запускается шагом 8 deploy/install.sh), которые лежат вне backend/.
COPY backend/pyproject.toml backend/pyproject.toml
RUN pip install --no-cache-dir ./backend

COPY backend/ backend/
COPY alembic/ alembic/
COPY scripts/ scripts/

WORKDIR /app/backend

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
# Прод-команда — без --reload (раздел 20: боевой инстанс, не дев-сервер);
# локальная разработка использует `uvicorn main:app --reload` напрямую
# (см. CLAUDE.md, раздел 4), не через этот образ.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

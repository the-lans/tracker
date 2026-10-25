FROM python:3.12-slim

# Один образ на backend, worker, beat и SFTP-шлюз (sftp, своя команда без
# миграций). Worker вызывает внешние программы:
# git и ssh — клонирование и пуш репозиториев задачи по deploy-ключу
# (services/git_ops.py), клиент Docker — script-ноды и уборка их контейнеров
# через docker.sock хоста (раздел 11.4, 16.2, 20.5).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker:27.5.1-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

# Build context — корень репозитория (см. docker-compose.yml:
# `build.context: .`, `build.dockerfile: backend/Dockerfile`), не backend/ —
# нужен доступ к корневому alembic/ (script_location = ../alembic, см.
# backend/alembic.ini) и repo-root scripts/ (seed_periodic_tasks.py,
# запускается шагом 8 deploy/install.sh), которые лежат вне backend/.
COPY backend/pyproject.toml backend/pyproject.toml
RUN pip install --no-cache-dir ./backend
# Claude Code CLI поставляется внутри claude-agent-sdk и в PATH не попадает.
# Команда `claude` нужна администратору для входа в каталоге LLM-аккаунта:
# docker compose exec -e CLAUDE_CONFIG_DIR=<каталог> worker claude auth login
# (раздел 19.5 ТЗ).
RUN ln -s "$(python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" /usr/local/bin/claude

COPY backend/ backend/
COPY alembic/ alembic/
COPY scripts/ scripts/
# Обёртка `cli_path` SDK: запускает CLI в контейнере сессии (раздел 19.3).
RUN chmod +x backend/session_cli.py

WORKDIR /app/backend

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
# Прод-команда — без --reload (раздел 20: боевой инстанс, не дев-сервер);
# локальная разработка использует `uvicorn main:app --reload` напрямую
# (см. CLAUDE.md, раздел 4), не через этот образ.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

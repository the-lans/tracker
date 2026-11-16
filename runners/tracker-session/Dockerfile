# Контейнер сессии — окружение процесса Claude Code CLI задачи (раздел 2.1,
# 19.3 ТЗ). Воркер сессий запускает его через обёртку backend/session_cli.py:
# монтирование каталогов задачи, лимиты, сеть и белый список переменных
# задаёт `docker run`, не образ.
FROM python:3.12-slim

# Инструменты, которыми агент работает в репозиториях задачи.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git openssh-client ripgrep procps curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# CLI — тот, что встроен в claude-agent-sdk той же версии, что у воркера
# (backend/pyproject.toml; совпадение проверяет tests/test_session_container.py).
ARG CLAUDE_AGENT_SDK_VERSION=0.2.180
RUN pip install --no-cache-dir "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}" \
    && ln -s "$(python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" /usr/local/bin/claude

WORKDIR /tmp

# Доступы пользователей при сборке не используются. Пакет закреплён lock-файлом.
COPY twg.lock.json install_twg.py /opt/tracker-twg-installer/
RUN python /opt/tracker-twg-installer/install_twg.py
ENV TWG_AGENT_DEFAULTS=1 TWG_CONFIG_DIR=/tmp/twg

# CLAUDE.md

Руководство для Claude Code при работе в этом репозитории. Источник истины по
требованиям — `docs/technical_specification.md`; этот файл —
краткая выжимка для повседневной разработки.

## 1. Назначение проекта

AI-трекер задач — веб-приложение для управления автоматизированными задачами
разработки, которые выполняются автономным AI-агентом (Claude Code) через
программное управление сессиями (Claude Agent SDK). Пользователь привязывает к
задаче Git-репозитории, выбирает пайплайн из нод (промт/слэш-команда/скрипт/
очистка контекста/режим планирования) и запускает его вручную или по
расписанию; каждая задача — ровно одна персистентная сессия Claude Code на
весь жизненный цикл.

## 2. Технологический стек

Версии со звёздочкой (*) не зафиксированы техническим заданием напрямую и
приняты как дефолт реализации; для backend/frontend они зафиксированы точно в
`backend/pyproject.toml` / `frontend/package.json` — этот раздел лишь
отражает их. При обновлении зависимостей обновляйте оба места.

### Backend (`backend/pyproject.toml`)
| Компонент | Версия |
|---|---|
| Python | 3.12* |
| FastAPI (async) | 0.115.6 |
| Uvicorn[standard] | 0.34.0* (ASGI-сервер, не назван в ТЗ напрямую) |
| SQLAlchemy (async) | 2.0.36 |
| asyncpg | 0.30.0* (асинхронный драйвер Postgres для SQLAlchemy async) |
| Alembic | 1.14.0 |
| Celery | 5.4.0 |
| redis-py | 5.2.1 |
| structlog | 24.4.0 |
| PostgreSQL | 15+ |
| pytest / pytest-asyncio | 8.3.4 / 0.25.0* |
| ruff | 0.8.4 |
| mypy | 1.14.1 |

### Frontend (`frontend/package.json`)
| Компонент | Версия |
|---|---|
| Node.js | 20 LTS* |
| React | 19.0.0 |
| react-dom | 19.0.0* |
| Vite | 6.0.7 |
| @vitejs/plugin-react | 4.3.4* |
| TanStack Query | 5.62.11 |
| shadcn (CLI) | 2.1.8 |
| Tailwind CSS / PostCSS / Autoprefixer | 3.4.17 / 8.4.49 / 10.4.20* (требуются shadcn/ui) |
| TypeScript | 5.7.2 |

ESLint и Vitest в package.json пока не заведены (не были явно названы в
разделе 2.2 ТЗ) — команды `npm run lint` / `npm test` появятся вместе с их
настройкой.

### Инфраструктура
| Компонент | Версия |
|---|---|
| Docker / Docker Compose | latest* |
| Caddy (reverse proxy) | 2.x* |
| Claude Agent SDK (Python) | `claude-agent-sdk`, latest* |

## 3. Структура репозитория

```
backend/
  api/       — HTTP-эндпоинты, валидация входных данных, сериализация ответов
  services/  — бизнес-логика: пайплайны, сессии, git-операции (min. 85% test coverage)
  db/        — ORM-модели, миграции
  clients/   — обёртки над Claude Agent SDK, GitLab API, MCP-серверами
  tasks/     — Celery-задачи (асинхронные и периодические)
  ws/        — WebSocket-обработчики real-time уведомлений
  logging/   — конфигурация structlog и запись в app_logs
frontend/    — React SPA (дашборд, страница задачи, админка)
deploy/
  caddy/     — конфигурация reverse-proxy
runners/
  tracker-runner-python/ — Docker-образ раннера для script-нод (Python)
  tracker-runner-bash/   — Docker-образ раннера для script-нод (Bash)
alembic/
  versions/  — миграции базы данных
docs/        — техническая документация, включая ТЗ
```

Файлы `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`,
`deploy/install.sh` предусмотрены разделом 20.3 ТЗ, но ещё не созданы —
появятся на этапе настройки инфраструктуры.

## 4. Команды

Backend требует Python **3.12+** (создайте venv явно нужной версией, если
системный `python3` старее). Прикладного кода пока нет — `backend/main.py` и
`frontend/src/main.tsx` это пустые точки входа ровно для того, чтобы
установка и дев-сервер были проверяемы уже сейчас.

### Установка зависимостей
```bash
# backend
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# frontend
cd frontend && npm install
```

### Дев-сервер
```bash
# backend (FastAPI, автоперезагрузка)
cd backend && uvicorn main:app --reload

# Celery worker / beat (появятся вместе с tasks/)
cd backend && celery -A tasks worker -l info
cd backend && celery -A tasks beat -l info

# frontend (Vite)
cd frontend && npm run dev

# полный стек локально
docker compose up -d
```

### Тесты
```bash
cd backend && pytest
cd frontend && npm test   # появится вместе с настройкой Vitest
```

### Линт
```bash
cd backend && ruff check .
cd frontend && npm run lint   # появится вместе с настройкой ESLint
```

### Тайпчек
```bash
cd backend && mypy .
cd frontend && npm run typecheck   # tsc --noEmit
```

### Миграции БД
```bash
cd backend && alembic revision --autogenerate -m "описание изменения"
cd backend && alembic upgrade head
```

## 5. Соглашения по именованию

- **Python-файлы и модули** — `snake_case.py`.
- **Тесты backend** — `test_*.py`, зеркалят структуру `services/`/`api/`.
- **React-компоненты** — `PascalCase.tsx` (один компонент на файл).
- **React-хуки** — `useCamelCase.ts`.
- **Тесты frontend** — `*.test.tsx` / `*.test.ts` рядом с исходником.
- **Таблицы БД** — `snake_case`, во множественном числе (`tasks`, `node_logs`).
- **Enum-значения** — `snake_case` (`plain_prompt`, `awaiting_input`).
- **Celery-задачи** — `snake_case`, глагол в начале (`check_scheduled_tasks_for_autostart`).
- **Шаблонные переменные** — `{{namespace.field}}`, namespace в нижнем
  регистре (`task`, `node`, `env`, `session`), `{{env.VAR_NAME}}` — сама
  переменная в UPPER_SNAKE_CASE.
- **Код задачи** — формат `RR-XXXXX`; рабочая ветка репозитория — формат
  `feature/RR-XXXXX`.
- **Git-коммиты** — Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`,
  `refactor:`, `test:`, `ci:`), тема в повелительном наклонении, без точки в
  конце.

## 6. Критичные правила проекта (нельзя нарушать)

1. **Одна сессия — один запрос за раз.** Обращения к `ClaudeSDKClient` строго
   последовательны через mutex на уровне Celery-задачи; параллельные ручные
   запросы идут через FIFO-очередь `task_manual_request_queue`, а не
   параллельно.
2. **Слэш-команды никогда не рендерятся шаблонизатором.** `command_invocation`
   передаётся в сессию буквально — правило действует одинаково в пайплайне,
   библиотеке и свободном вводе.
3. **MCP-сервер с состоянием обязан иметь изоляцию.** Сохранение
   `has_stateful_resource = true` с `isolation_mode = NULL`/`none` запрещено
   валидацией API. Общий persistent-профиль между задачами недопустим ни при
   каких обстоятельствах.
4. **Script-ноды — без сети и без лишних привилегий.** Контейнер запускается
   без сетевого доступа (без исключений), монтируется только директория
   репозиториев текущей задачи (read-write), обязательны лимиты CPU/памяти,
   `--privileged` не используется.
5. **Очистка рабочей директории репозиториев — только вручную и только в
   терминальном статусе** (`done`/`failed`). Автоматическое удаление
   запрещено.
6. **Очистка контекста сессии (`clear_context`) запрещена**, пока существует
   хотя бы одна запись `node_logs` со статусом `running`/`awaiting_decision`.
7. **Retry применяется только к нодам пайплайна** (`trigger_type = pipeline`)
   и никогда — к запускам из библиотеки промтов или к решению «Доработать
   план».
8. **Секреты хранятся только зашифрованными**, ключ шифрования — вне БД
   (переменная окружения сервера). Значения скрыты в UI по умолчанию.
9. **Удаление вместо архивации запрещено** для: пайплайна, используемого хотя
   бы одной задачей; системного промта, привязанного хотя бы к одной задаче;
   репозитория, привязанного к активной задаче. Разрешена только архивация.
10. **Создание `task_nodes` при привязке пайплайна — атомарно**, в одной
    транзакции вместе с `tasks.pipeline_id`; частичный снимок недопустим.
11. **Редактирование состава нод задачи** разрешено свободно только в
    статусе `new`; в `failed` — только для нод с `order_index >
    tasks.last_failed_order_index`.
12. **Celery-задачи обязаны быть идемпотентными**: проверка текущего
    состояния перед изменением, распределённая блокировка Redis (`SET NX` +
    TTL) для критичных операций (пуш в Git, push-уведомления, обработка
    очереди).
13. **Покрытие тестами `backend/services/`** — не ниже 85%.
14. **Переход в `done`** невозможен, пока хотя бы одна включённая нода
    пайплайна не имеет записи `node_logs` со статусом `success`.
15. **Backend не обращается к содержимому Confluence-страниц** из поля
    `guide_url` — это ответственность LLM через MCP, не backend.

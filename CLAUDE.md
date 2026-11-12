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
весь жизненный цикл (задача из одних скриптов без стартового LLM-аккаунта
работает без сессии). Трафик моделей идёт через LLM-прокси CLIProxyAPI: аккаунты
провайдеров (Claude, Codex и др.) подключаются входом OAuth из UI, у аккаунта —
модель и уровень рассуждений по умолчанию; трекер сам выбирает аккаунт хода
так, чтобы 5-часовые окна стартовали с равным шагом и порог из профиля не
переступался, а когда все аккаунты на пороге — задача ждёт сброса лимита
(статус «Ждёт лимита»). Форму задачи можно заполнить из Jira;
файлы задачи — артефакты, доступные агенту, скриптам, UI и по SFTP. После
зелёного CI на `main` сервер обновляется сам (GitHub Actions → SSH).

## 2. Технологический стек

Версии со звёздочкой (*) не зафиксированы техническим заданием напрямую и
приняты как дефолт реализации; для backend/frontend они зафиксированы точно в
`backend/pyproject.toml` / `frontend/package.json` — этот раздел лишь
отражает их.

**Обновление версий не ручное**: `.github/dependabot.yml` еженедельно
проверяет pip- (backend/), npm- (frontend/), Docker- и GitHub Actions-
зависимости и открывает PR при выходе новых релизов. Сам CLAUDE.md
dependabot не трогает — после слияния таких PR таблицы ниже нужно
синхронизировать с `backend/pyproject.toml` / `frontend/package.json`
вручную. Версию `claude-agent-sdk` в `ARG CLAUDE_AGENT_SDK_VERSION`
образа `runners/tracker-session/Dockerfile` dependabot тоже не меняет —
её поднимают в том же PR (CLI сессии должен совпадать с SDK воркера,
`test_session_image_cli_matches_worker_sdk`). Несовместимые обновления исключены через `ignore` в
`dependabot.yml` (TypeScript ≥ 6.1, `@vitejs/plugin-react` 6.1.2, смена
minor/major Python в Docker, нечётные не-LTS версии Node). Ручная сверка: `pip index versions <pkg>` (в
`.venv`) / `npm view <pkg> version`; перед приёмом мажорного апдейта — `pip
check` / `npm ls`, чтобы поймать конфликт версий до мержа.

### Backend (`backend/pyproject.toml`)
| Компонент | Версия |
|---|---|
| Python | 3.12* |
| FastAPI (async) | 0.162.0 |
| Uvicorn[standard] | 0.54.0* (ASGI-сервер, не назван в ТЗ напрямую) |
| SQLAlchemy (async) | 2.1.8 |
| asyncpg | 0.32.0* (асинхронный драйвер Postgres для SQLAlchemy async) |
| Alembic | 1.20.1 |
| Celery | 5.7.0 |
| redis-py | 8.1.0 |
| structlog | 26.1.0 |
| claude-agent-sdk | 0.2.178 |
| asyncssh | 2.24.1* (SFTP-шлюз, раздел 19.6) |
| httpx | 0.28.1* (клиенты GitLab и Jira, тесты API) |
| cryptography | 50.0.2* (шифрование секретов и токена сессии, раздел 19.4) |
| google-auth | 2.62.1* (проверка Google id_token, раздел 19.1) |
| pywebpush | 2.5.0* (Web Push, раздел 18.1) |
| boto3 | 1.43.127* (выгрузка резервных копий в S3, раздел 20.4) |
| PostgreSQL | 15+ |
| pytest / pytest-asyncio / pytest-cov | 9.2.0 / 1.4.1.post1* / 7.1.0* |
| ruff | 0.17.3 |
| mypy | 2.4.1 |

### Frontend (`frontend/package.json`)
| Компонент | Версия |
|---|---|
| Node.js | 26* (образ сборки `frontend/Dockerfile`; CI — 22) |
| React | 19.3.1 |
| react-dom | 19.3.1* |
| Vite | 8.3.5 |
| @vitejs/plugin-react | 6.1.1* |
| TanStack Query | 5.105.0 |
| shadcn (CLI) | 4.23.0 |
| Tailwind CSS / PostCSS / Autoprefixer | 4.3.3 / 8.5.32 / 10.6.2* (требуются shadcn/ui) |
| TypeScript | 6.0.3 |
| ESLint / typescript-eslint | 10.13.0 / 8.72.1 |
| Vitest / jsdom | 5.0.5* / 30.1.3* |
| Testing Library (react / dom / jest-dom / user-event) | 16.3.3* / 10.4.2* / 7.0.1* / 14.6.8* |

TypeScript закреплён на 6.0.3, а не на новом мажоре 7.x: `typescript-eslint@8.72.1`
пока требует `typescript < 6.1.0` (проверено `npm view typescript-eslint
peerDependencies`) — апгрейд до TS 7 ждёт апгрейда этой цепочки, иначе
`npm ls` покажет конфликт. `@vitejs/plugin-react` закреплён на 6.1.1:
6.1.2 через optional peer-зависимости тянет `@babel/core@8` и ломает
разрешение зависимостей (ERESOLVE). Тесты фронтенда — Vitest в окружении
jsdom и Testing Library (ТЗ 21.1); настройка — секция `test` в
`vite.config.ts`, общая подготовка — `src/test/setup.ts`.

### Инфраструктура
| Компонент | Версия |
|---|---|
| Docker / Docker Compose | latest* |
| Caddy (reverse proxy) | 2.x* |
| CLIProxyAPI (LLM-прокси) | v8.0.48 — `CLIPROXY_VERSION` в `.env.example`; образ собирается из `github.com/router-for-me/CLIProxyAPI` на теге, dependabot его не отслеживает |
| Claude Agent SDK (Python) | `claude-agent-sdk`, версия — в таблице Backend |

## 3. Структура репозитория

```
backend/
  api/       — HTTP-эндпоинты, валидация входных данных, сериализация ответов
              (auth, tasks, repositories, templates, preview, llm_accounts,
              env_variables, mcp_servers, pipelines, nodes, users, profile,
              periodic_tasks, monitoring — страница «Мониторинг», events —
              лента событий, push, system_settings, jira,
              llm_proxy — состояние LLM-прокси для админки);
              tasks/ — эндпоинты задачи по разделам (crud, lifecycle, nodes,
              manual, env_variables, artifacts; common.py — доступ к задаче
              и сигнал воркеру); dependencies.py — текущий пользователь и
              require_admin; schemas/ — схемы запросов и ответов по разделам
              (импорт — `from api.schemas import …`)
  services/  — бизнес-логика: пайплайны, сессии, git-операции (min. 85% test coverage);
              access.py — владение записями «своё или admin» (раздел 19.2),
              включая LLM-аккаунты; pipeline_validation.py — проверка ноды и
              всего пайплайна при сохранении (раздел 5.1); task_artifacts.py —
              артефакты задачи в volume user_files и проверка пути
              resolve_inside (раздел 14.3); sftp_access.py — правила входа и
              видимости задач SFTP-шлюза (раздел 19.6); task_codes.py и
              repository_validation.py — коды задач, git_url, имена
              репозиториев и веток, безопасные для путей и git (раздел 3.1);
              task_launch.py — проверки перед запуском, в т. ч. LLM-аккаунт
              только для LLM-нод; task_editing.py — правка полей задачи;
              очередь задач (раздел 14.4): task_queue.py — слоты автора,
              порядок очереди, ночное окно, ручная смена статуса;
              task_dispatcher.py — проход дневного и ночного воркера
              очереди; refining_chat.py — чат с агентом в «Уточняется»;
              template_files.py — файлы шаблона, загруженные с диска;
              jira_import.py — импорт задачи из Jira (раздел 15.6);
              LLM-прокси (раздел 19.7): llm_providers.py — реестр
              провайдеров (уровни рассуждений, опрос расхода, план-режим);
              llm_accounts.py и llm_account_login.py — аккаунты, порядок
              переключения, вход OAuth через прокси; llm_usage.py — расход
              5-часового и недельного окна, средняя стоимость хода;
              llm_routing.py — токен сессии и маршрут хода;
              llm_account_choice.py — чистое правило выбора: состояние лимита
              аккаунта, шаг окон, срочность, ожидание; account_router.py —
              аккаунт каждого хода задачи, ворота лимита, сжатие контекста
              при смене; limit_wait.py — статус `awaiting_limit`: ворота
              лимита по типу хода (скрипт и очистка контекста их не
              ждут), вход, возврат с попыткой ждавшей ноды, остановка и
              пауза ожидания; llm_limit_state.py —
              состояние лимита аккаунтов для списка; llm_account_checks.py — периодическая
              сверка аккаунтов с прокси; llm_proxy_admin.py — состояние прокси
              для админки; claude_config.py — каталог сессии задачи
              (`CLAUDE_SESSIONS_ROOT/<код>`); maintenance.py — флаг
              обслуживания `maintenance:deploy` на время обновления сервера;
              session_history_migration.py — перенос истории сессий из
              каталогов прежних LLM-аккаунтов (раздел 20.6);
              library_links.py — нода пайплайна со ссылкой на промт
              библиотеки: привязка, содержимое и аргументы запуска (раздел 7.6);
              events.py — запись и выборка ленты событий (раздел 18.4; пишет
              только notifications.py, вместе с push); «Мониторинг»
              (раздел 15.5): server_status.py — сводка сервера, node_stats.py —
              статистика нод за период, llm_usage_summary.py — расход и
              переключения LLM-аккаунтов, volume_usage.py — замер volume
              (в Redis) и место на диске, container_monitor.py — контейнеры
              задач и признак «осиротел» (общий с purge_* в maintenance_tasks.py);
              backup/ — резервные копии в S3 (раздел 20.4): settings.py —
              настройки и их проверка, storage.py — клиент S3 с повторами,
              components.py — состав копии (= архивы install.sh --restore),
              archive.py — tar.gz volume с пропуском меняющихся файлов,
              dump.py — pg_dump, crypto_gpg.py — шифрование паролем,
              bundle.py — каталог копии (manifest.json, SHA256SUMS,
              after-restore.sql, restore.sh и RESTORE.md из templates/),
              runner.py — бэкап с ротацией, verify.py — проверка
              восстановления во временном postgres:15, runs.py — общая
              блокировка, записи backup_runs и уведомления, jobs.py — запуск
              из периодических задач;
              nodes/ — выполнение нод (dispatch.py, script.py — Docker-раннер,
              clear_context.py); plan_mode.py — callback разрешений SDK:
              решение по плану, вопросы агента, режимы разрешений (раздел 9);
              template_context.py — рендер переменных (RenderedText: текст для
              сессии и замаскированный для показа); session_container.py —
              аргументы контейнера сессии (раздел 19.3), docker_mounts.py —
              монтирование каталогов задачи в контейнеры script-нод и сессии;
              child_rebase.py — ребейз дочерней ветки воркером по
              `rebase_requested_at`; session_heartbeat.py — пульс и единственный
              владелец сессии; node_history.py — история `node_logs` задачи
              для `{{node.*}}` и вкладки «Логи»; node_runs.py — жизненный
              цикл записи `node_logs` (старт, итог, остановка);
              redis_connection.py — клиент Redis на операцию; integrity.py —
              запреты удаления (раздел 3.2) и commit_or_conflict
  db/        — ORM-модели (db/base.py — Base), асинхронное подключение
              (db/session.py — engine/session из DATABASE_URL)
  clients/   — обёртки над Claude Agent SDK (claude_agent.py, в т. ч.
              OfflineAgentClient для задач без LLM-аккаунта и маршрут хода
              TurnRouter), GitLab API (gitlab.py), Jira REST API (jira.py),
              management API LLM-прокси (cliproxy.py), классы HTTP-сбоев
              внешних API (http_errors.py); конфигурация MCP-серверов
              для сессии — services/mcp_config.py
  llm_gateway/ — шлюз между контейнером сессии и LLM-прокси (сервис
              `llm-gateway`, `python -m llm_gateway`): по токену сессии
              подставляет учётку прокси, модель и уровень рассуждений
              маршрута задачи (rewrite.py), ответ передаёт потоком
  tasks/     — Celery-приложение и задачи: celery_app.py (include модулей,
              очереди sessions и backups, DatabaseScheduler), session_worker.py
              (долгоживущая сессия задачи), periodic.py / periodic_scheduler.py,
              jira_attachments.py (вложения Jira → артефакты, в фоне),
              async_runner.py — run_with_fresh_pool: асинхронное тело задачи
              в своём event loop с пустым пулом БД (правило 12)
  session_cli.py — обёртка `cli_path` SDK: запускает Claude Code CLI в
              контейнере сессии `tracker-session` (белый список окружения)
  docker-entrypoint.sh — применяет alembic-миграции и создаёт роль БД
              SFTP-шлюза перед стартом backend/worker/session-worker/beat
  sftp_gateway/ — SFTP-шлюз (сервис `sftp`, `python -m sftp_gateway`):
              asyncssh-сервер, вход по ключу (auth.py), виртуальная ФС
              /<код>/repos (только чтение) и /<код>/artifacts (filesystem.py),
              ключ хоста (host_key.py), роль БД tracker_sftp (db_role.py,
              вызывается из docker-entrypoint.sh)
  ws/        — WebSocket-обработчики real-time уведомлений (tasks.py —
              `/ws/tasks/{task_id}/status`: смена статуса, смена текущего
              LLM-аккаунта задачи — событие `llm_account`, начало и конец
              чата в «Уточняется» — событие `chat` — и потоковый вывод
              ответа LLM, разделы 14.4, 15.2, 18.1)
  app_logging/ — конфигурация structlog (config.py) и запись в app_logs
              вне транзакции вызывающего кода (app_logs.py) (не "logging" —
              так называется модуль stdlib, вложенный пакет с этим именем
              внутри backend/ его перекрывает)
  alembic.ini — конфиг Alembic (async); script_location указывает на
              корневой alembic/ (см. ниже), строку подключения задаёт
              alembic/env.py из DATABASE_URL, а не сам alembic.ini
  tests/     — pytest (test_*.py, плоско; conftest.py поднимает Postgres и
              Redis в Docker, fakes.py — фейки Claude Agent SDK,
              factories.py — общие тестовые записи (автор, LLM-аккаунт, эталонные SSH-ключи),
              cliproxy_support.py — фейк management API LLM-прокси,
              s3_support.py — фейк S3, backup_support.py — окружение бэкапа,
              git_support.py — локальные bare-репозитории и коммиты для тестов git,
              worker_support.py — обвязка воркера сессии для его тестов и E2E)
frontend/    — React SPA: дашборд, страница задачи (обзор + диалог),
              конструктор пайплайна/библиотека, CRUD-страницы
              (репозитории/шаблоны/LLM-аккаунты/переменные окружения),
              админка (раздел 15.5, в т. ч. вкладка «LLM-прокси»), страница
              «Мониторинг» (components/monitoring) и лента «События»
              (components/events, раздел 18.4), Web Push (public/service-worker.js,
              src/lib/push.ts, раздел 18.1); Dockerfile + nginx.conf —
              продовый образ (сборка на Node, раздача nginx с SPA-фолбэком
              на index.html для клиентских маршрутов). Общие элементы — по
              типам: components/ui (примитивы), components/common/{actions,
              avatar,dialogs,feedback,filters,navigation,typography},
              components/layout; повторяющиеся механики — общими
              компонентами: navigation/PageTabs (вкладки страницы в `?tab=`,
              хук hooks/useUrlTab.ts) и SegmentedControl, filters/FilterSelect
              (фильтр «Все/значение»), feedback/QueryState (загрузка, ошибка
              или содержимое) и ErrorState, tasks/TaskCodeLink (код задачи
              ссылкой);
              по разделам — components/{tasks,nodes,profile,admin,
              repositories,templates,llmAccounts,envVariables};
              styles/tokens.css + index.css — токены (цвета, шкала шрифтов
              text-caption…text-display), styles/classes.ts — общие наборы
              классов; lib/labels.ts — все подписи и цвета статусов;
              lib/taskStatusTransitions.ts — статусы до запуска и ручные
              переходы (зеркало services/task_queue.py);
              lib/errors.ts — текст и тост ошибки API (errorMessage,
              toastError); hooks/useInvalidatingMutation.ts — мутация с
              перечитыванием списков; common/dialogs/EntityFormDialog —
              диалог создания/правки записи справочника; src/test/ — общее
              для тестов Vitest: fixtures.ts (`test` с фикстурами api и
              toasts, как conftest.py), factories.ts (тестовые записи),
              apiMock.ts (подмена fetch с записью запросов),
              renderWithProviders.tsx (кеш запросов, роутер и вошедший
              пользователь; renderHookWithClient — для хуков),
              fakeWebSocket.ts (подмена WebSocket), setup.ts
deploy/
  caddy/     — конфигурация reverse-proxy (handle_path /api/* — срезает
              префикс перед проксированием на backend)
  cliproxy/  — LLM-прокси: config.template.yaml (обязательные настройки
              трекера) и init.sh — сервис `cliproxy-init`, при каждом старте
              рендерит конфигурацию с ключами из `.env` в volume cliproxy_data
  backup/    — встроенный сервис локальных дампов PostgreSQL по
              расписанию (раздел 20.4): Dockerfile, entrypoint.sh (crond),
              backup.sh (pg_dump + ротация по POSTGRES_BACKUP_RETENTION_DAYS)
  install.sh — единственный скрипт установки по разделу 20.2 ТЗ;
              `--restore <каталог>` — перенос на новый сервер (раздел 20.4):
              дамп БД и архивы volume task_repos, user_files, log_archive,
              claude_sessions, cliproxy_data, claude_accounts, sftp_host_keys;
              `--update [--ref <sha>] [--wait-idle <мин>]` — обновление
              установленного сервера (раздел 20.6): флаг обслуживания,
              ожидание живых сессий, коммит из origin/main, пересборка всех
              образов (в т. ч. раннеров и tracker-session), дамп БД,
              `.deploy/previous_ref`, `DEPLOYED_AT` в `.env`, миграции,
              перенос истории сессий; при откате — данные новой версии в
              понятный прежней вид (статусы, ссылки на библиотеку); код
              выхода 3 — отменено, сервер не изменён
  ci_deploy.sh — принудительная команда SSH-ключа развёртывания (раздел
              20.7): только `deploy <sha> [--force | --wait-idle <мин>]` и
              `previous-ref`
runners/
  tracker-runner-python/ — Docker-образ раннера для script-нод (Python)
  tracker-runner-bash/   — Docker-образ раннера для script-нод (Bash)
  tracker-session/       — Docker-образ контейнера сессии: процесс Claude
              Code CLI задачи (раздел 19.3), запускается обёрткой `cli_path`
alembic/
  env.py       — async env (target_metadata = db.base.Base.metadata)
  versions/    — миграции базы данных (полная схема раздела 3.1,
                 push_subscriptions, nodes.llm_output_last_n, статус paused,
                 task_parent_summaries, system_settings, владельцы записей,
                 SFTP, токен GitLab в system_settings, уникальность
                 task_nodes, подключение к Jira, tasks.reset_at, адрес Jira
                 в system_settings, task_repositories.rebase_requested_at,
                 tasks.context_cleared_at, task_nodes.pause_after, nodes.task_id —
                 свои ноды задачи, node_logs.decision_output_offset — место
                 решения в ответе, node_logs.error_message — причина
                 ошибки, LLM-прокси: провайдер, учётка и порядок аккаунтов,
                 расход окон, пороги пользователя, nodes.reasoning_effort,
                 tasks.current_llm_account_id, аккаунт, модель и уровень хода
                 в node_logs, доступ к GitLab API в git_credentials,
                 статусы до запуска, очередь и слоты задач, лимит
                 пользователя, ночное окно, tasks.chat_active,
                 templates.uploaded_file_paths, контроль лимитов:
                 статус awaiting_limit и поля ожидания задачи (в т. ч.
                 попытка ждущей ноды), старт окна
                 и стоимость хода аккаунта, сжатие при смене аккаунта,
                 бэкап в S3: настройки в system_settings и backup_runs,
                 таблица events, nodes.library_node_id и library_arguments,
                 индекс app_logs.created_at);
                 новые миграции пишут DDL
                 с IF [NOT] EXISTS, чтобы повторный запуск не падал
scripts/
  verify_sdk.py — точечная проверка claude-agent-sdk (не часть пайплайна
                приложения), запускать backend-venv'ом, см. раздел 4
  seed_admin_allowlist.py — заполняет `allowed_emails` email'ом первого
                администратора (запускается install.sh ДО первого входа —
                без этого войти в систему не может никто, раздел 19.1)
  migrate_claude_sessions.py — перенос истории сессий задач из каталогов
                прежних LLM-аккаунтов (`install.sh --update`/`--restore`,
                идемпотентен)
  seed_periodic_tasks.py  — заполняет `periodic_tasks` (раздел 16.2);
                запускается install.sh на шаге 8, до первого входа
                (`updated_by = NULL`), повторный запуск идемпотентен
  smoke_frontend_image.sh — собирает продовый образ фронтенда и проверяет
                SPA-фолбэк nginx (запускается в CI после make check)
  qa/          — стенд ручного E2E-тестирования (docs/qa_e2e_manual.md):
                stand.sh (.env из qa.env с VAPID-ключами,
                compose-проект tracker-qa, git-хост qa-git по SSH и мок
                qa-mocks в его сети, справочники, сертификат Caddy;
                env/seed/up/data/trust/merge/export/down), qa.env.example —
                шаблон настроек и секретов стенда (копия qa.env — в
                .gitignore), seed_qa_data.py — справочники и эталонный
                пайплайн, pipeline/ — скрипты его script-нод,
                mock_providers.py — мок Jira и GitLab API, git-server/ —
                образ git-хоста, seed/qa-calc — тестовый репозиторий
docs/        — техническая документация: ТЗ, implementation_plan.md (план
              реализации по этапам), migration.md (раздел 20.4 — процедура
              переноса на новый сервер), deployment.md (разделы 20.6–20.7 —
              подготовка сервера к автоматическому развёртыванию), qa_e2e_manual.md (ручное E2E-
              тестирование в браузере), remote_control_findings.md
              (верификация допущения раздела 6.3 и проверка LLM-прокси), design/ (HTML-референсы
              дашборда и страницы задачи), screen/ (скриншоты страницы задачи)
.github/     — workflows/ci.yml (сборка образов раннеров → make check →
              smoke-тест образа фронтенда), workflows/deploy.yml
              (развёртывание после зелёного CI на main, раздел 20.7;
              scripts/verify_deployment.sh — проверка /api/health и
              index.html, откат на previous_ref) и dependabot.yml
docker-compose.yml, docker-compose.prod.yml, .env.example — раздел 20.3 ТЗ
.mcp.json    — MCP-серверы для Claude Code (раздел 4 ниже)
.claude/commands/ — команды-промты /promt-* для работы в Claude Code
.playwright-mcp/  — сценарии и снимки Playwright MCP (в .gitignore)
```

## 4. Команды

Backend требует Python **3.12+** (создайте venv явно нужной версией, если
системный `python3` старее).

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

# Celery: периодические задачи, сессии задач и бэкапы (свои очереди), планировщик
cd backend && celery -A tasks.celery_app worker -Q celery -l info
cd backend && celery -A tasks.celery_app worker -Q sessions -O fair -l info
cd backend && celery -A tasks.celery_app worker -Q backups -c 1 -l info
cd backend && celery -A tasks.celery_app beat -l info

# шлюз сессий к LLM-прокси (нужны REDIS_URL, CLIPROXY_URL, CLIPROXY_API_KEY)
cd backend && python -m llm_gateway

# frontend (Vite)
cd frontend && npm run dev

# полный стек локально
docker compose up -d
```

### Единая проверка (лит + тайпчек + тесты, backend и frontend)
```bash
make check
```
Создаёт/актуализирует `backend/.venv` и `frontend/node_modules` при
необходимости, затем последовательно: `ruff check .` → `mypy .` → `pytest`
(backend; падает, если покрытие `services/` ниже 85%), `eslint .` → `tsc --noEmit` → `vitest run` (frontend). Падает с ненулевым кодом
на первой же ошибке. CI (`.github/workflows/ci.yml`) дополнительно перед
ней собирает образы раннеров, а после — запускает
`scripts/smoke_frontend_image.sh`.

### Тесты
```bash
cd backend && .venv/bin/pytest
cd frontend && npm test   # Vitest, один прогон; npm run test:watch — в режиме наблюдения
scripts/smoke_frontend_image.sh   # продовый образ фронтенда + SPA-маршруты
```
Backend-тестам нужен запущенный Docker: `conftest.py` сам поднимает
тестовые Postgres (порт 55432) и Redis (55379) в контейнерах, а тесты
script-нод запускают образы раннеров — их нужно собрать заранее (и
пересобирать после правок `runners/`):
```bash
docker build -t tracker-runner-python:latest runners/tracker-runner-python/
docker build -t tracker-runner-bash:latest runners/tracker-runner-bash/
docker build -t tracker-session:latest runners/tracker-session/
```

### Линт
```bash
cd backend && .venv/bin/ruff check .
cd frontend && npm run lint
```

### Тайпчек
```bash
cd backend && .venv/bin/mypy .
cd frontend && npm run typecheck   # tsc --noEmit
```

### Миграции БД
```bash
cd backend && alembic revision --autogenerate -m "описание изменения"
cd backend && alembic upgrade head
```

### Вход в LLM-аккаунт (раздел 19.5)
Только из интерфейса: «LLM-аккаунты» → «Добавить» (пометка и провайдер) →
«Войти» — ссылка провайдера, после входа адрес, на который провайдер вернул
браузер, вставляется в диалог; затем выбираются модель и уровень рассуждений
по умолчанию. Токены хранит LLM-прокси (volume `cliproxy_data`), консоль
сервера не нужна. Состояние прокси и учёток — «Администрирование» →
«LLM-прокси».

### Обновление сервера (разделы 20.6–20.7)
```bash
deploy/install.sh --update [--ref <sha>] [--wait-idle <минуты>]
```
После зелёного CI на `main` это делает `.github/workflows/deploy.yml`
(подготовка сервера — `docs/deployment.md`).

### Доступ к файлам задач по SFTP (раздел 19.6)
Администратор назначает пользователю логин SFTP (`os_username`) в разделе
«Пользователи», пользователь добавляет SSH-ключ в профиле — инструкция с
отпечатком сервера там же. Подключение как диска:
```bash
sshfs -p 2222 <логин>@<домен>:/ ~/tracker -o reconnect
```

### Проверка claude-agent-sdk
```bash
backend/.venv/bin/python scripts/verify_sdk.py
```
Требует рабочего логина Claude Code на машине (использует уже
аутентифицированный CLI, отдельный API-ключ не нужен).

### MCP-серверы для Claude Code (`.mcp.json`)

`playwright`/`context7` работают без настройки. `postgres` (Postgres MCP Pro,
`crystaldba/postgres-mcp` через `uvx`) требует переменную окружения
`DATABASE_URI` в шелле перед запуском Claude Code (например, тестовый
Postgres из `backend/tests/conftest.py`:
`postgresql://tracker:testpass@localhost:55432/tracker`; у Postgres в
`docker-compose.yml` порт наружу не проброшен); без нужного
диапазона версий пакета зависает на несовместимой `mcp 2.x` — версия
0.3.0 явно закреплена через `uvx --with "mcp<2"`, это учтено в конфиге.

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
- **Код задачи** — любой текст без пробелов (например, `RR-12345` или ключ
  Jira), проверка — `services/task_codes.py`; рабочая ветка репозитория —
  `feature/<код>`.
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
   без сетевого доступа (без исключений), монтируются только директория
   репозиториев и каталог артефактов текущей задачи (read-write; из
   контейнера worker — подпутём volume, найденного через `docker inspect`),
   обязательны лимиты CPU/памяти,
   `--privileged` не используется. Переменные задачи передаются все; токен
   GitLab API — в учётных данных Git (`git_credentials`), а не переменная, и в
   контейнер не попадает. Пути задачи — в `TASK_REPOS_PATH` и
   `TASK_ARTIFACTS_PATH` (текст скрипта не шаблонизируется). Процесс
   Claude Code CLI — тоже в контейнере (`tracker-session`, ТЗ 19.3): только
   репозитории, артефакты и каталог сессии задачи
   (`CLAUDE_SESSIONS_ROOT/<код>`), окружение по белому списку (токен сессии
   вместо ключей провайдера), сеть — одна `llm_sessions`, где кроме
   контейнеров сессий лишь `llm-gateway` (к модели — только через него), с
   выходом в интернет для MCP-серверов; без `docker.sock`, ключей шифрования и
   внутренней сети сервисов.
   Git воркера не исполняет код из репозитория: без хуков, без системного и
   глобального конфига, локальный `.git/config` — по белому списку.
5. **Очистка рабочей директории репозиториев — только вручную и только в
   терминальном статусе** (`done`/`failed`). Автоматическое удаление
   запрещено.
6. **Очистка контекста сессии (`clear_context`) запрещена**, пока существует
   хотя бы одна запись `node_logs` со статусом `running`/`awaiting_decision`.
7. **Retry применяется только к нодам пайплайна** (`trigger_type = pipeline`)
   и никогда — к запускам из библиотеки промтов или к решению «Доработать
   план».
8. **Секреты хранятся только зашифрованными**, ключ шифрования — вне БД
   (переменная окружения сервера). Значения скрыты в UI по умолчанию, в
   предпросмотре промта и в `node_logs.rendered_prompt` — замаскированы
   (`RenderedText.display`); в сессию уходит настоящее значение.
9. **Удаление вместо архивации запрещено** для: пайплайна, используемого хотя
   бы одной задачей; системного промта, привязанного хотя бы к одной задаче.
   Разрешена только архивация. Ноду, которую использует задача,
   LLM-аккаунт, выбранный у задачи, и репозиторий, привязанный к любой
   задаче (`task_repositories` — её история), удалить нельзя — 409 (ТЗ 3.2);
   репозиторий активной задачи нельзя и переименовать.
10. **Создание `task_nodes` при привязке пайплайна — атомарно**, в одной
    транзакции вместе с `tasks.pipeline_id`; частичный снимок недопустим.
11. **Редактирование состава нод задачи** разрешено свободно только в
    статусах до запуска (`new`, `refining`, `defined`, `ready`,
    `night_worker`; там же пайплайн меняется — снимок заменяется целиком;
    после запуска — возвратом из `failed`/`done` в статус до запуска,
    `POST /tasks/{id}/status`); в `failed` — только для нод с `order_index >
    tasks.last_failed_order_index` и для ноды на самой точке перезапуска,
    если она не начинала выполняться в текущем прогоне (остановка на паузе
    после ноды ставит точку сразу за ней) (`services/task_nodes.py`,
    `PATCH /tasks/{id}/nodes/{task_node_id}`). По тем же правилам между
    нодами снимка вставляются, правятся и удаляются свои промты задачи
    (`nodes.task_id`, `POST`/`DELETE /tasks/{id}/nodes…`); своя нода с
    историей `node_logs` не удаляется. Отметка «пауза после»
    (`task_nodes.pause_after`) — управление прогоном, а не состав: меняется
    в любом статусе, после успеха ноды задача встаёт в `paused`.
12. **Celery-задачи обязаны быть идемпотентными**: проверка текущего
    состояния перед изменением, распределённая блокировка Redis (`SET NX` +
    TTL) для критичных операций (пуш в Git, обработка очереди ручных
    запросов, проход воркера очереди задач `services/task_dispatcher.py`).
    Push-уведомление отправляется только после фиксации однократного
    изменения состояния (compare-and-swap статуса и т. п.), а событие,
    которое может повториться, — под ключом `SET NX` с TTL (ТЗ 17.4).
    Асинхронное тело Celery-задачи запускается через
    `tasks/async_runner.run_with_fresh_pool`, а не голым `asyncio.run`:
    иначе вторая задача процесса получит соединение пула чужого event loop.
    У сессии задачи один владелец: ключ пульса ставится `SET NX` с
    токеном и продлевается/снимается только им; повторно доставленное
    продолжение ждёт освобождения ограниченное время и выходит без
    эффектов, `visibility_timeout` брокера больше этого ожидания.
13. **Покрытие тестами `backend/services/`** — не ниже 85%.
14. **Переход в `done`** невозможен, пока хотя бы одна включённая нода
    пайплайна не имеет записи `node_logs` со статусом `success` в текущем
    прогоне: после возврата из `failed`/`done` в статус до запуска записи
    раньше `tasks.reset_at` не считаются ни здесь, ни в точке перезапуска.
    Статусы до запуска меняет только пользователь
    (`services/task_queue.change_task_status_manually`), статусы выполнения —
    только система; `failed` слот параллельного запуска не освобождает.
    Переход в `failed` обязан зафиксировать `tasks.last_failed_order_index`
    (`order_index` упавшей ноды); все статусные переходы — через
    compare-and-swap текущего статуса в транзакции БД.
15. **Backend не обращается к содержимому Confluence-страниц** из поля
    `guide_url` — это ответственность LLM через MCP, не backend.
    Единственное исключение — импорт задачи Jira по ключу (раздел 15.6):
    по явному запросу пользователя и его личным токеном, только с сервера
    из `system_settings.jira_url` (адрес задаёт администратор).
16. **Сессией задачи управляет только её воркер** (`tasks/session_worker.py`).
    API не трогает сессию и не меняет статусы `in_progress`/`paused`
    напрямую: ручные промты кладёт в очередь, команды pause/resume/stop —
    в Redis (`services/task_control.py`), и будит воркер сигналом. Воркер
    перед каждой нодой выполняет запрошенное переподключение моста, затем
    выполняет запрошенный ребейз (`task_repositories.rebase_requested_at`)
    и обрабатывает конфликт ребейза, очередь ручных запросов FIFO и команды;
    статус `paused` — решение пользователя, см.
    `docs/implementation_plan.md`, п. 6. `claude.ai/code` — только для
    просмотра сессии: ввод в сессию идёт только через трекер (п. 8); через
    LLM-прокси мост недоступен (`remote_control_status = unavailable`) —
    его не проверяют и не переподключают.
    Задача, у которой пропал пульс сессии (`services/session_heartbeat.py`),
    после исчерпания попыток переходит в `failed` (ТЗ 6.6).
    В `awaiting_limit` и обратно задачу переводит воркер, пока держит пульс;
    у ждущей задачи воркера нет, поэтому «Остановить» и «Приостановить» в
    ожидании выполняет API (`services/limit_wait.py`, compare-and-swap).
    Чат в `refining` (ТЗ 14.4) — тоже только воркер, режим `chat_only`:
    ручные запросы без пайплайна, статус остаётся `refining` (ожидание
    ответа — через `awaiting_input`/`plan_review` и обратно), признак
    `tasks.chat_active` ставит и снимает только он
    (`services/refining_chat.py`); сбой чата или потеря его пульса
    возвращает задачу в `refining`, а не в `failed`. Перед новым проходом
    чата очищается команда управления предыдущим прогоном. Доставка задач
    очереди повторяется по сохранённому `queued`; `queued_only=true` запрещает
    позднему дублю перезапускать `failed`. Обновление с `--wait-idle` ждёт
    и активные чаты (`chat_active=true`).
17. **Режимы разрешений агента** (`services/plan_mode.py`, ТЗ 9): пока идёт
    нода `plan_prompt`, правки запрещены, а принятый план завершает ход
    ноды без изменений — реализуют следующие ноды; `current_permission_mode =
    default` — каждое действие, требующее разрешения, ждёт «Разрешить» /
    «Запретить» в виджете; `NULL`/`acceptEdits` — автономная работа.
    Вопросы агента (`AskUserQuestion`) — в формате SDK: `questions[]` →
    `answers`.
18. **Всё, что попадает в путь или командную строку git, проверяется до
    использования**: код задачи (`services/task_codes.py`), `git_url`, имя
    репозитория и базовая ветка (`services/repository_validation.py`);
    позиционные аргументы git — после `--`.
19. **Трафик моделей — только через LLM-прокси** (ТЗ 19.7). Сессия ходит к
    модели через `llm-gateway` по токену сессии (`services/llm_routing.py`,
    в Redis — только sha256 токена), шлюз подставляет учётку, модель и
    уровень маршрута задачи. Токены OAuth провайдеров хранит только
    CLIProxyAPI (volume `cliproxy_data`), в БД — лишь имя учётки. Аккаунт
    каждого хода выбирает `services/account_router.py`
    (`services/llm_account_choice.py`): порог 5-часового окна из профиля
    автора не переступается, недельного порога нет; если все аккаунты на
    пороге или исчерпаны, ход модели не начинается — задача ждёт сброса
    (`awaiting_limit`); ворота учитывают тип хода, скрипт и очистка
    контекста их не ждут, пересказ родителя ждёт вместе с задачей. Смена аккаунта на границе хода сжимает контекст
    (`/compact`, буквально) по переключателю профиля;
    `tasks.current_llm_account_id` выставляет только воркер (compare-and-swap);
    сбрасывается лишь до запуска — возврат из `failed`/`done` в статус до
    запуска и смена стартового аккаунта.
    Конфигурацию прокси задаёт репозиторий (`deploy/cliproxy/`) — трекер не
    меняет её через management API.
20. **Миграция релиза только добавляет** (ТЗ 20.6): откат
    (`install.sh --update --ref`, автоматический — в `deploy.yml`)
    возвращает код и образы, а схема БД остаётся новой. Удаление и
    переименование столбцов, которыми пользуется предыдущая версия, — не
    раньше следующего релиза.

# Перенос на новый сервер

Раздел 20.4 ТЗ: "смена сервера должна сводиться к переносу файла `.env` и
volume-данных, без изменений кода или повторной ручной настройки окружения".
Ниже — конкретная процедура для этого проекта.

## Что переносится

| Что | Где живёт | Как переносится |
|---|---|---|
| `.env` | `${INSTALL_DIR}/.env` на старом сервере | Копируется файлом напрямую |
| Данные PostgreSQL | volume `postgres_data` | Через дамп `pg_dump`/`pg_restore` (см. ниже) — не архивом сырых файлов данных, т.к. версия PostgreSQL на новом сервере обязана совпадать для архивного переноса, а дамп независим от версии |
| Репозитории задач (включая профили MCP-инструментов, раздел 10.3) | volume `task_repos` | Архив `tar` |
| Пользовательские файлы задач | volume `user_files` | Архив `tar` |
| Архив истории выполнения (`rotate_task_logs`, раздел 16.2) | volume `log_archive` | Архив `tar` |
| Входы в Claude и история сессий LLM-аккаунтов (разделы 6.4, 19.5) | volume `claude_accounts` | Архив `tar` |
| TLS-сертификаты Caddy | volumes `caddy_data`/`caddy_config` | Не переносятся — Caddy сам перевыпустит сертификат на новом сервере при первом запуске (раздел 20.2, шаг 10); перенос усложнил бы процедуру без реальной пользы |

## Процедура

### На старом сервере

1. Снять внеплановый дамп БД (не дожидаясь расписания `POSTGRES_BACKUP_CRON`):

   ```bash
   cd /opt/tracker
   docker compose exec backup /usr/local/bin/backup.sh
   ```

   Дамп появится в volume `postgres_backups`, файл `tracker-<UTC-таймстамп>.sql.gz`.

2. Заархивировать volume-данные и скопировать вместе с `.env` и последним дампом на новый сервер (пример через `docker run` + `tar`, без остановки сервисов — репозитории задач не должны меняться на лету во время архивации, поэтому короткая пауза `worker`/`beat` разумна для консистентности архива `task_repos`):

   ```bash
   docker compose stop worker beat
   docker run --rm -v tracker_task_repos:/data -v "$(pwd)":/backup alpine \
     tar czf /backup/task_repos.tar.gz -C /data .
   docker run --rm -v tracker_user_files:/data -v "$(pwd)":/backup alpine \
     tar czf /backup/user_files.tar.gz -C /data .
   docker run --rm -v tracker_log_archive:/data -v "$(pwd)":/backup alpine \
     tar czf /backup/log_archive.tar.gz -C /data .
   docker run --rm -v tracker_claude_accounts:/data -v "$(pwd)":/backup alpine \
     tar czf /backup/claude_accounts.tar.gz -C /data .
   docker compose start worker beat

   docker cp "$(docker compose ps -q backup)":/backups/<файл-дампа>.sql.gz ./
   ```

   Перенести на новый сервер: `.env`, `task_repos.tar.gz`, `user_files.tar.gz`,
   `log_archive.tar.gz`, `claude_accounts.tar.gz` (входы в Claude и история сессий LLM-аккаунтов; у сервера версии без volume `claude_accounts` этого архива нет — восстановление его пропустит),
   `<файл-дампа>.sql.gz` (например, `scp`).

### На новом сервере

3. Сложить перенесённые файлы в один каталог, например `/root/transfer`:
   `.env`, `<файл-дампа>.sql.gz`, `task_repos.tar.gz`, `user_files.tar.gz`,
   `log_archive.tar.gz`, `claude_accounts.tar.gz`.
4. Запустить `deploy/install.sh` (тот же скрипт, что и для обычной
   установки, раздел 20.2) в режиме восстановления:

   ```bash
   bash install.sh --restore /root/transfer
   ```

   Скрипт сначала проверяет, что в каталоге есть все пять файлов (если
   дампов несколько — берёт самый свежий по имени), и только потом:
   ставит Docker при необходимости, клонирует репозиторий, кладёт
   перенесённый `.env` в `${INSTALL_DIR}/.env` (прежний, если был,
   сохраняется как `.env.before-restore`), собирает образы, поднимает
   PostgreSQL и Redis, восстанавливает дамп в пустую БД **до** миграций,
   распаковывает архивы в volumes `task_repos`/`user_files`/`log_archive`/`claude_accounts` через сервис
   `backend`, применяет миграции и запускает прикладные сервисы. Генерация
   секретов, интерактивные вопросы и seed пропускаются: всё это уже есть
   в `.env` и дампе.

   Важно: `SECRET_ENCRYPTION_KEY`/`SESSION_SECRET_KEY` обязаны быть теми же,
   что на старом сервере, — иначе расшифровка перенесённых
   `env_variables.value_encrypted`/`repositories.deploy_key_encrypted`/
   `mcp_servers.auth_config_encrypted` не сработает (раздел 3.2, 19.4).
   Поэтому `.env` берётся из каталога переноса, а не генерируется.

5. Открыть `https://<DOMAIN>` и войти тем же Google-аккаунтом администратора,
   что и на старом сервере — восстановленная БД уже содержит его в `users`,
   повторная регистрация не требуется.

### Ручное восстановление (если скрипт неприменим)

Тот же порядок вручную: положить `.env` в `${INSTALL_DIR}/.env`, выполнить
обычный `deploy/install.sh` (генерация `.env` пропустится — файл уже есть),
затем остановить прикладные сервисы и восстановить данные:

```bash
cd /opt/tracker
docker compose stop backend worker beat

docker run --rm -v tracker_task_repos:/data -v "$(pwd)":/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/task_repos.tar.gz -C /data"
docker run --rm -v tracker_user_files:/data -v "$(pwd)":/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/user_files.tar.gz -C /data"
docker run --rm -v tracker_log_archive:/data -v "$(pwd)":/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/log_archive.tar.gz -C /data"
docker run --rm -v tracker_claude_accounts:/data -v "$(pwd)":/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/claude_accounts.tar.gz -C /data"

docker compose up -d --wait postgres
zcat <файл-дампа>.sql.gz | docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
docker compose up -d backend worker beat frontend caddy backup
```

В этом варианте миграции уже применены к пустой БД до восстановления
дампа — дамп со старого сервера должен быть снят с той же версией схемы.

## Проверка после переноса

- `docker compose ps` — все сервисы `healthy`/`running`, включая `backup`.
- Открыть несколько существующих задач в UI — история `node_logs` и статус
  видны (подтверждает восстановление дампа БД).
- Запустить существующую задачу с уже клонированным репозиторием — рабочая
  директория на месте (подтверждает восстановление `task_repos`).
- `docker compose logs backup` — расписание из `.env` подхвачено
  (`[entrypoint.sh] расписание: ...`), а не дефолт.

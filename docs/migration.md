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
   docker compose start worker beat

   docker cp "$(docker compose ps -q backup)":/backups/<файл-дампа>.sql.gz ./
   ```

   Перенести на новый сервер: `.env`, `task_repos.tar.gz`, `user_files.tar.gz`,
   `<файл-дампа>.sql.gz` (например, `scp`).

### На новом сервере

3. Выполнить `deploy/install.sh` обычным образом (раздел 20.2) — **кроме**
   шага генерации `.env`: положить перенесённый `.env` в `${INSTALL_DIR}/.env`
   до запуска скрипта — `step_generate_env` пропускает генерацию, если файл
   уже существует, поэтому секреты/ключи со старого сервера сохранятся
   (важно: `SECRET_ENCRYPTION_KEY`/`SESSION_SECRET_KEY` обязаны быть теми же,
   иначе расшифровка перенесённых `env_variables.value_encrypted`/
   `repositories.deploy_key_encrypted`/`mcp_servers.auth_config_encrypted`
   не сработает — раздел 3.2, 19.4).
4. Остановить прикладные сервисы (если `install.sh` уже успел их поднять) и
   восстановить volume-данные и дамп БД **до** первого реального использования:

   ```bash
   cd /opt/tracker
   docker compose stop backend worker beat

   docker run --rm -v tracker_task_repos:/data -v "$(pwd)":/backup alpine \
     sh -c "rm -rf /data/* && tar xzf /backup/task_repos.tar.gz -C /data"
   docker run --rm -v tracker_user_files:/data -v "$(pwd)":/backup alpine \
     sh -c "rm -rf /data/* && tar xzf /backup/user_files.tar.gz -C /data"

   docker compose up -d --wait postgres
   zcat <файл-дампа>.sql.gz | docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
   ```

5. Запустить прикладные сервисы: `docker compose up -d backend worker beat frontend caddy backup`.
6. Открыть `https://<DOMAIN>` и войти тем же Google-аккаунтом администратора,
   что и на старом сервере — восстановленная БД уже содержит его в `users`,
   повторная регистрация не требуется.

## Проверка после переноса

- `docker compose ps` — все сервисы `healthy`/`running`, включая `backup`.
- Открыть несколько существующих задач в UI — история `node_logs` и статус
  видны (подтверждает восстановление дампа БД).
- Запустить существующую задачу с уже клонированным репозиторием — рабочая
  директория на месте (подтверждает восстановление `task_repos`).
- `docker compose logs backup` — расписание из `.env` подхвачено
  (`[entrypoint.sh] расписание: ...`), а не дефолт.

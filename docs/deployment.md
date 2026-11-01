# Развёртывание и обновление сервера

Раздел 20.6–20.7 ТЗ. Первая установка — вручную `deploy/install.sh`
(раздел 20.2); дальше сервер обновляется сам после каждого слияния в `main`
с зелёным CI, а вручную — тем же `deploy/install.sh --update`.

## Как устроено

1. CI (`.github/workflows/ci.yml`) успешно прошёл на push в `main`.
2. Workflow `.github/workflows/deploy.yml` в GitHub Environment `production`
   подключается к серверу по SSH ключом развёртывания и передаёт одну
   строку: `deploy <sha> --wait-idle <минуты>` (или `--force` при ручном
   запуске с флагом «не ждать»).
3. На сервере ключ ограничен принудительной командой `deploy/ci_deploy.sh`:
   она проверяет строку и выполняет
   `deploy/install.sh --update --ref <sha> --wait-idle <минуты>`.
4. `install.sh --update` ставит флаг обслуживания (запуск задач отвечает 503,
   воркер не берёт задачи из очереди), ждёт завершения живых сессий,
   переходит на коммит, пересобирает образы, снимает дамп БД, применяет
   миграции, переносит историю сессий и перезапускает сервисы.
5. Workflow ждёт до 5 минут, пока `https://<домен>/api/health` не вернёт SHA
   развёрнутого коммита и фронтенд не отдаст `index.html`. При неудаче он
   откатывается на коммит из `.deploy/previous_ref` (`deploy <sha> --force`);
   схема БД при откате остаётся новой.

Коды выхода `install.sh --update`: `0` — обновлено; `3` — обновление
отменено до перехода на новый код (живые сессии не завершились за отведённое
время, коммит не из `main`, переходу мешают локальные правки) — сервер не
изменён, откат не нужен; другой — ошибка после перехода, workflow откатывает.

## Подготовка сервера

Выполняется один раз после первой установки, от root.

### 1. Пользователь развёртывания

```bash
useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
chown -R deploy:deploy /opt/tracker
```

Группа `docker` даёт права, равные root на хосте: ключ этого пользователя
хранится только в секретах окружения GitHub. Каталог установки должен
принадлежать ему — `install.sh` меняет в нём код, `.env` и `.deploy/`.

### 2. Ключ развёртывания

На своей машине (не на сервере):

```bash
ssh-keygen -t ed25519 -N "" -C "tracker-deploy" -f tracker_deploy_key
```

Открытый ключ — в `~deploy/.ssh/authorized_keys` на сервере одной строкой с
принудительной командой:

```text
command="/opt/tracker/deploy/ci_deploy.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA… tracker-deploy
```

```bash
install -d -m 700 -o deploy -g deploy ~deploy/.ssh
chmod 600 ~deploy/.ssh/authorized_keys && chown deploy:deploy ~deploy/.ssh/authorized_keys
```

Закрытый ключ `tracker_deploy_key` — только в секрет
`DEPLOY_SSH_PRIVATE_KEY` (шаг 4), затем удалить локальную копию.

### 3. Ключ хоста

Строка `known_hosts` для проверки сервера (отключать проверку хоста нельзя):

```bash
ssh-keyscan -p 22 tracker.example.com
```

Сверьте отпечаток с выводом на самом сервере:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

### 4. GitHub Environment `production`

Settings → Environments → `production`. По желанию — Required reviewers: каждое
развёртывание будет ждать подтверждения.

| Имя | Тип | Значение |
|---|---|---|
| `DEPLOY_ENABLED` | variable | `true` — включить автоматическое развёртывание |
| `DEPLOY_HOST` | variable | Адрес сервера для SSH |
| `DEPLOY_PORT` | variable | Порт SSH, по умолчанию `22` |
| `DEPLOY_USER` | variable | `deploy` (шаг 1) |
| `DEPLOY_DOMAIN` | variable | Домен трекера, тот же, что `DOMAIN` в `.env` сервера |
| `DEPLOY_WAIT_IDLE_MINUTES` | variable | Сколько ждать завершения живых сессий, по умолчанию `60` |
| `DEPLOY_SSH_PRIVATE_KEY` | secret | Закрытый ключ шага 2 |
| `DEPLOY_SSH_KNOWN_HOSTS` | secret | Строка шага 3 |

Пока `DEPLOY_ENABLED` не `true`, workflow завершается без действий.
Секреты приложения (`.env`: ключи шифрования, OAuth Google, ключи
LLM-прокси) в GitHub не передаются — они только на сервере, новые
переменные дописывает `install.sh --update`.

### 5. Защита `main`

Settings → Branches → правило для `main`: обязательный зелёный CI перед
слиянием. Развёртывание запускается только после успешного CI, но защита
ветки не даёт слить в неё красный код вовсе.

### 6. Проверка

Actions → Deploy → Run workflow (ветка `main`, без параметров). В summary
задания — коммит, длительность и откат, если он был. Проверка ключа вручную:

```bash
ssh -i tracker_deploy_key deploy@tracker.example.com previous-ref
```

## Ручные операции

```bash
cd /opt/tracker
deploy/install.sh --update                          # вершина origin/main
deploy/install.sh --update --wait-idle 30           # дождаться живых сессий
deploy/install.sh --update --ref <sha>              # конкретный коммит из main
deploy/install.sh --update --ref "$(cat .deploy/previous_ref)"   # откат
```

Ручной запуск workflow с `ref` разворачивает указанный коммит из `main`, с
`force` — не ждёт завершения живых сессий: они прервутся и перейдут в
`failed`, их продолжают «Перезапустить с текущей ноды».

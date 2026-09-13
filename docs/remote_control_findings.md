# Программное управление мостом `/remote-control` — результаты проверки

Верификация допущения из раздела 6.3 ТЗ: «команда `/remote-control` в реальном
использовании может подразумевать интерактивное продолжение текущей CLI-сессии,
а не исключительно программный вызов через готовый API». Ниже — что удалось
установить эмпирически (Claude Code CLI 2.1.270, `claude-agent-sdk` 0.2.152)
перед тем, как проектировать разделы 6.5–6.6 (кнопка переподключения,
автомониторинг) вокруг этого механизма.

## Итог одним предложением

**`/remote-control` — это не слэш-команда**, а CLI-флаг `--remote-control
[name]`, задаваемый только при **старте** процесса `claude`; SDK может
прокинуть его через `ClaudeAgentOptions.extra_args`, но не предоставляет
никакого метода для проверки статуса моста или его переподключения **во время
уже идущей сессии** — в отличие от аналогичного механизма для MCP-серверов
(`reconnect_mcp_server`/`get_mcp_status`), у которого такой метод есть.

## Что проверено и подтверждено

1. **Текст ТЗ вводит в заблуждение неймингом.** В самом `claude`
   (`claude --help`) нет слэш-команды и нет отдельного подкоманд-раздела
   `remote-control` — это флаг верхнего уровня:
   ```
   --remote-control [name]               Start an interactive session with Remote
                                          Control enabled (optionally named)
   --remote-control-session-name-prefix <prefix>
       Prefix for auto-generated Remote Control session names (default: hostname)
   ```
   Полный список подкоманд (`claude --help`, секция `Commands:`) подтверждает:
   отдельной команды `remote-control` (в духе `claude mcp`, `claude attach`)
   не существует вовсе.

2. **Формулировка `--help` явно говорит про «interactive session».** Это
   прямое текстуальное указание на риск, отмеченный в ТЗ: флаг документирован
   как поведение интерактивной сессии, а не как программный API-переключатель.

3. **В исходниках `claude-agent-sdk` (Python) нет ни одного упоминания
   remote control.**
   ```
   grep -rniE "remote.control|remote_control|remotecontrol" \
     backend/.venv/lib/python3.12/site-packages/claude_agent_sdk
   # → 0 совпадений
   ```
   Полный список публичных методов `ClaudeSDKClient` (`client.py`): `connect`,
   `query`, `receive_messages`, `receive_response`, `interrupt`,
   `set_permission_mode`, `set_model`, `rewind_files`, `reconnect_mcp_server`,
   `toggle_mcp_server`, `stop_task`, `get_mcp_status`, `get_context_usage`,
   `get_server_info`, `disconnect`. Ничего похожего на
   `reconnect_remote_control()` или `get_remote_control_status()` нет — при
   том, что для MCP-серверов симметричная пара
   (`reconnect_mcp_server`/`get_mcp_status`) присутствует. Это asymmetric
   API — сильный сигнал, что remote control сознательно не выведен в control
   protocol SDK.

4. **Флаг можно прокинуть в подпроцесс через `extra_args`.**
   `ClaudeAgentOptions.extra_args: dict[str, Any] | None` транслируется в
   CLI-аргументы на этапе построения команды подпроцесса
   (`_internal/transport/subprocess_cli.py`, метод `_build_command`,
   выполняется один раз при `connect()`):
   ```python
   options = ClaudeAgentOptions(extra_args={"remote-control": "sdk-probe"})
   ```
   → `cmd.append("--remote-control=sdk-probe")` (значение без ведущего `-`
   попадает в форму `--flag value`; см. код сериализации — для булевых флагов
   без значения используется просто `--flag`).

5. **Живой запуск через SDK с этим флагом не падает.** Прогнал сессию
   (`ClaudeSDKClient` + `extra_args={"remote-control": "sdk-probe"}`,
   `stderr`-коллбек для диагностики) — сессия штатно прошла весь цикл
   (`RateLimitEvent` → `SystemMessage(subtype='init')` → `AssistantMessage` →
   `ResultMessage(subtype='success')`), stderr пуст, ошибок парсинга CLI-флага
   не было. Значит связка «SDK (`--output-format stream-json --verbose`) +
   `--remote-control`» как минимум не является взаимоисключающей на уровне
   запуска процесса.

6. **Но payload `SystemMessage(subtype='init')` не содержит ни одного поля
   про remote control.** Это самое информативное системное сообщение сессии
   (перечисляет `tools`, `mcp_servers` со статусами, `slash_commands`,
   `capabilities`, `session_id` и т.д.) — там же логично было бы ожидать
   `remoteControlStatus`/`remoteControlUrl`, если бы SDK-протокол это
   поддерживал. Поля нет. `SystemMessage.subtype` в SDK типизирован как
   произвольная строка (`subtype: str; data: dict[str, Any]`), то есть CLI
   технически мог бы прислать отдельное системное сообщение с другим
   `subtype` при изменении статуса моста — но такого подтипа среди известных
   (`init`, `task_started`, `task_progress`, `task_notification`,
   `task_updated`, `mirror_error`, `hook_event` — единственные, оформленные
   отдельными датаклассами в `types.py`) нет.

## Что осталось неподтверждённым (требует ручной проверки в браузере)

Я не могу headless проверить, действительно ли сессия, запущенная через SDK с
`--remote-control`, реально становится управляемой с `claude.ai/code` — для
этого нужен человек, залогиненный в тот же аккаунт, который откроет
`claude.ai/code` и посмотрит, появляется ли там сессия с именем `sdk-probe` и
можно ли из неё реально слать команды. Это следующий шаг верификации,
который я не закрыл в рамках этой задачи.

## Практический вывод для проектирования разделов 6.5–6.6

- **`tasks.session_id` пересоздавать нельзя** (раздел 6.1) — а единственный
  подтверждённый способ включить Remote Control требует флага **на старте**
  процесса. Значит для секции 6.5 («Переподключить удалённую сессию») есть
  ровно два пути, и оба требуют компромисса:
  1. **Всегда** передавать `extra_args={"remote-control": ...}` при первом
     `connect()` задачи — мост, если он вообще работает в SDK-режиме,
     включён с самого начала жизненного цикла сессии; кнопка «Переподключить»
     в этом случае не может дёрнуть SDK-метод (его нет) — она может максимум
     показать текущий статус и подсказать пользователю открыть
     `claude.ai/code` заново (переподключение на стороне браузера, не сессии).
  2. Полный **restart** процесса `claude` (`disconnect()` + новый `connect()`
     с новым `extra_args`) — обходит отсутствие runtime-API, но требует либо
     нарушить правило «`session_id` не пересоздаётся», либо использовать
     `ClaudeAgentOptions.resume=<session_id>` при новом `connect()`, чтобы
     возобновить тот же диалог новым процессом (это отдельно не проверено).
- **`remote_control_status` (`connected`/`disconnected`/`reconnecting`) в
  БД нельзя достоверно обновлять из потока сообщений SDK** — раз в `init` и
  других типизированных системных сообщениях этого поля нет, backend не
  может узнать реальный статус моста иначе как через недокументированное
  поведение. Раздел 6.6 (`check_remote_control_bridges`) в текущем виде
  спроектирован вокруг несуществующего программного индикатора.
- **Рекомендация**: прежде чем кодировать 6.5/6.6, either (a) получить от
  Anthropic/из репозитория `claude-agent-sdk-python` подтверждение
  дорожной карты по remote control в control protocol, либо (b) закладывать
  в архитектуру, что «статус моста» и «переподключение» — это факты со
  стороны `claude.ai/code`, а не то, что backend может достоверно
  знать/вызывать через `ClaudeSDKClient`, и переосмыслить UI-сценарий кнопки
  6.5 как «открыть свежую ссылку на `claude.ai/code» вместо «дёрнуть
  reconnect на сессии».

## Как воспроизвести проверку

```bash
cd backend && .venv/bin/pip install -e ".[dev]"   # claude-agent-sdk==0.2.152

# 1) убедиться, что /remote-control — CLI-флаг, а не слэш-команда
claude --help | grep -A2 "remote-control"

# 2) убедиться, что SDK не знает о remote control
grep -rniE "remote.control|remote_control" .venv/lib/python3.12/site-packages/claude_agent_sdk

# 3) живой пробный запуск с флагом через extra_args (см. вывод сообщений
#    сессии и содержимое SystemMessage(subtype='init'))
.venv/bin/python - <<'PY'
import asyncio
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

async def main():
    options = ClaudeAgentOptions(extra_args={"remote-control": "sdk-probe"})
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Ответь словом OK")
        async for message in client.receive_response():
            print(type(message).__name__, message)

asyncio.run(main())
PY
```

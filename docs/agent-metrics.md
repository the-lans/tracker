# Метрики агентных сессий

Tracker пока не использует отдельный Prometheus/OpenTelemetry-сборщик. Метрики
пишутся как структурированные JSON-события текущего логгера. Для событий
сессии логгер автоматически добавляет `task_id`, если вызов выполняется в
контексте задачи.

## События и поля

### Запуск и остановка CLI

События `session_connected` и `session_disconnected` содержат:

| Поле | Смысл |
| --- | --- |
| `duration_ms` | Время подключения или отключения CLI-процесса. |

Событие `session_client_replaced` фиксирует замену CLI-клиента. Оно не содержит
числовых показателей.

### Ход Claude SDK

Событие `session_query_started` содержит:

| Поле | Смысл |
| --- | --- |
| `prompt_length` | Длина отправленного промпта в символах. Содержимое промпта не записывается. |

Событие `session_query_finished` содержит следующие поля:

| Поле | Смысл |
| --- | --- |
| `status` | `success`, `error` или `cancelled`. |
| `is_error` | Флаг ошибки из `ResultMessage`; есть только у штатно полученного результата. |
| `duration_ms` | Время от отправки промпта до завершения, ошибки SDK или отмены. |
| `time_to_first_event_ms` | Время до первого события SDK; `null`, если событие не пришло. |
| `tool_call_count` | Число `ToolUseBlock` в ходе, включая MCP, Bash и встроенные инструменты. |
| `subagent_call_count` | Число инструментов с именем `Agent` или `Task`. |
| `tool_error_count` | Число полученных `ToolResultBlock` с `is_error=true`. |
| `tool_duration_total_ms` | Сумма длительностей полученных результатов инструментов. |
| `tool_duration_max_ms` | Максимальная длительность полученного результата инструмента. |
| `assistant_error` | Тип ошибки ассистента, если SDK его сообщил. |
| `session_id` | Идентификатор сессии из `ResultMessage`; есть только у штатного результата. |

При исключении SDK или отмене хода итоговое событие всё равно записывается со
статусом `error` или `cancelled`. В этом случае поля, связанные с отсутствующим
`ResultMessage`, не заполняются.

### Инструменты в диагностическом режиме

При `CLAUDE_DIAGNOSTICS=true` записываются:

| Событие | Поля | Назначение |
| --- | --- | --- |
| `session_tool_started` | `tool_name`, `tool_input`, `parent_tool_use_id` | Найти последний начавшийся инструмент. |
| `session_tool_log_limit_reached` | `limit` | Показать, что подробные tool-события были ограничены. |
| `claude_cli_stderr` | `line` | Сохранить короткую строку stderr CLI. |

`tool_input` ограничен 200 символами и рекурсивно маскирует поля, содержащие
`token`, `secret`, `password`, `authorization`, `credential`, `cookie` или
`private_key`. Подробно записывается не более 50 tool-событий на ход.

### Management API CLIProxy

Событие `cliproxy_management_request_finished` создаётся для запросов
`CliproxyManagementClient` к `/v8/management`:

| Поле | Смысл |
| --- | --- |
| `method` | HTTP-метод management API. |
| `path` | Путь management API без тела запроса и секретов. |
| `status` | HTTP-код или `transport_error`. |
| `duration_ms` | Время HTTP-запроса. |

Это метрика management API CLIProxy, а не latency генерации модели. Фактическое
время ответа Claude через gateway отдельно пока не измеряется.

## Диагностическая конфигурация

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `CLAUDE_DIAGNOSTICS` | `false` | Включить подробные tool-события, stderr и ограничения диагностики. |
| `CLAUDE_DIAGNOSTICS_MAX_TURNS` | `20` | Максимальное число ходов Claude CLI в диагностическом режиме. Некорректное или неположительное значение заменяется на `20`. |

В диагностическом режиме запрещены `Agent`, `Task`, `Bash` и `ListAgents`.
Обычные задачи при выключенном флаге не получают эти ограничения.

Для worker-контейнеров Compose ограничивает Docker logs: один файл — до 50 МБ,
хранится не более трёх файлов. Это ограничивает расход диска при временном
включении диагностики.

## Интерпретация

1. `session_query_started` без `session_query_finished` означает открытый или
   прерванный ход.
2. Большой `time_to_first_event_ms` указывает задержку до первого события SDK.
3. Большой `duration_ms` при большом `tool_call_count` указывает широкий обход.
4. `subagent_call_count > 0` означает делегирование через `Agent`/`Task`.
5. Последнее `session_tool_started` — кандидат на медленный или зависший вызов.
6. `tool_duration_*` и `tool_error_count` рассчитываются только для полученных
   `ToolResultBlock`; незавершённые вызовы в сумму не входят.
7. `cliproxy_management_request_finished` нельзя использовать как latency
   ответа модели.

Claude CLI запускается с `replay-user-messages`, чтобы SDK мог передать
`UserMessage` и `ToolResultBlock` для расчёта длительности инструментов. Если
конкретная версия CLI их не пересылает, счётчики вызовов продолжают работать,
а длительности остаются `null`/`0` и не означают быстрый вызов.

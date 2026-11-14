import {
  AppLogLevel,
  BackupRunStatus,
  NodeLogStatus,
  NodeLogTriggerType,
  NodeType,
  EnvVariableScope,
  LlmAccountStatus,
  LlmLimitState,
  LlmSwitchReason,
  McpIsolationMode,
  PeriodicRunStatus,
  ReasoningEffort,
  RemoteControlStatus,
  RepositoryRole,
  UserRole,
  type NodeItem,
} from "@/lib/types";
import { EventCategory } from "@/lib/events.types";
import type { DayFact, GoogleCalendarStatus } from "@/lib/daily.types";
import { ContainerKind, ServerDependency, StatsPeriod, VolumeName } from "@/lib/monitoring.types";

/** Человекочитаемые подписи значений enum — в интерфейсе не показываем внутренние коды. */

/** Цвет бейджа статуса (варианты `Badge`). */
export type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral";

export const USER_ROLE_LABEL: Record<UserRole, string> = {
  [UserRole.ADMIN]: "Администратор",
  [UserRole.USER]: "Пользователь",
};

export const LLM_ACCOUNT_STATUS_LABEL: Record<LlmAccountStatus, string> = {
  [LlmAccountStatus.LOGIN_REQUIRED]: "нужен вход",
  [LlmAccountStatus.ACTIVE]: "активен",
  [LlmAccountStatus.RATE_LIMITED]: "упёрся в лимит",
  [LlmAccountStatus.DISABLED]: "отключён",
};

export const ENV_SCOPE_LABEL: Record<EnvVariableScope, string> = {
  [EnvVariableScope.GLOBAL]: "глобальная",
  [EnvVariableScope.REPOSITORY]: "репозиторий",
};

export const PERIODIC_RUN_STATUS_LABEL: Record<PeriodicRunStatus, string> = {
  [PeriodicRunStatus.SUCCESS]: "успешно",
  [PeriodicRunStatus.FAILED]: "ошибка",
  [PeriodicRunStatus.RUNNING]: "выполняется",
};

export const MCP_ISOLATION_LABEL: Record<McpIsolationMode, string> = {
  [McpIsolationMode.NONE]: "без изоляции",
  [McpIsolationMode.ISOLATED_FLAG]: "изолированный режим",
  [McpIsolationMode.PER_TASK_DATA_DIR]: "своя папка у задачи",
};

export const APP_LOG_LEVEL_LABEL: Record<AppLogLevel, string> = {
  [AppLogLevel.DEBUG]: "отладка",
  [AppLogLevel.INFO]: "инфо",
  [AppLogLevel.WARNING]: "предупреждение",
  [AppLogLevel.ERROR]: "ошибка",
  [AppLogLevel.CRITICAL]: "критично",
};

export const REPOSITORY_ROLE_LABEL: Record<RepositoryRole, string> = {
  [RepositoryRole.READ_WRITE]: "чтение и запись",
  [RepositoryRole.READ_ONLY]: "только чтение",
};

/** Раздел 15.1: состояние лимита аккаунта (раздел 19.7). */
export const LLM_LIMIT_STATE_LABEL: Record<LlmLimitState, string> = {
  [LlmLimitState.RUNNING]: "Запущен",
  [LlmLimitState.FREE]: "Свободен",
  [LlmLimitState.AT_THRESHOLD]: "На пороге",
  [LlmLimitState.EXHAUSTED]: "Исчерпан",
  [LlmLimitState.EXCLUDED]: "Не участвует",
};

export const LLM_LIMIT_STATE_TONE: Record<LlmLimitState, BadgeTone> = {
  [LlmLimitState.RUNNING]: "info",
  [LlmLimitState.FREE]: "success",
  [LlmLimitState.AT_THRESHOLD]: "warning",
  [LlmLimitState.EXHAUSTED]: "danger",
  [LlmLimitState.EXCLUDED]: "neutral",
};

export const LLM_ACCOUNT_STATUS_TONE: Record<LlmAccountStatus, BadgeTone> = {
  [LlmAccountStatus.LOGIN_REQUIRED]: "warning",
  [LlmAccountStatus.ACTIVE]: "success",
  [LlmAccountStatus.RATE_LIMITED]: "warning",
  [LlmAccountStatus.DISABLED]: "danger",
};

export const PERIODIC_RUN_STATUS_TONE: Record<PeriodicRunStatus, BadgeTone> = {
  [PeriodicRunStatus.SUCCESS]: "success",
  [PeriodicRunStatus.FAILED]: "danger",
  [PeriodicRunStatus.RUNNING]: "info",
};

export const BACKUP_RUN_STATUS_LABEL: Record<BackupRunStatus, string> = {
  [BackupRunStatus.RUNNING]: "Выполняется",
  [BackupRunStatus.SUCCESS]: "Успешно",
  [BackupRunStatus.WARNING]: "С пропусками",
  [BackupRunStatus.FAILED]: "Ошибка",
};

export const BACKUP_RUN_STATUS_TONE: Record<BackupRunStatus, BadgeTone> = {
  [BackupRunStatus.RUNNING]: "info",
  [BackupRunStatus.SUCCESS]: "success",
  [BackupRunStatus.WARNING]: "warning",
  [BackupRunStatus.FAILED]: "danger",
};

export const APP_LOG_LEVEL_TONE: Record<AppLogLevel, BadgeTone> = {
  [AppLogLevel.CRITICAL]: "danger",
  [AppLogLevel.ERROR]: "danger",
  [AppLogLevel.WARNING]: "warning",
  [AppLogLevel.INFO]: "info",
  [AppLogLevel.DEBUG]: "neutral",
};

/** Тип ноды пайплайна. */
export const NODE_TYPE_LABEL: Record<NodeType, string> = {
  [NodeType.PLAIN_PROMPT]: "Обычный промт",
  [NodeType.SLASH_COMMAND]: "Слэш-команда",
  [NodeType.SCRIPT]: "Скрипт",
  [NodeType.CLEAR_CONTEXT]: "Очистить контекст",
  [NodeType.PLAN_PROMPT]: "Режим планирования",
};

/** Раздел 7.6: тип ноды пайплайна, которая выполняет промт библиотеки. */
export const LIBRARY_PROMPT_LABEL = "Промт из библиотеки";

/** Тип ноды в списках: нода со ссылкой на библиотеку — «Промт из библиотеки» (раздел 7.6). */
export function nodeTypeLabel(node: Pick<NodeItem, "node_type" | "library_node_id">): string {
  return node.library_node_id ? LIBRARY_PROMPT_LABEL : NODE_TYPE_LABEL[node.node_type];
}

/** Раздел 13.4: источник записи истории — для фильтров и таблицы «Логи». */
export const NODE_LOG_TRIGGER_LABEL: Record<NodeLogTriggerType, string> = {
  [NodeLogTriggerType.PIPELINE]: "Пайплайн",
  [NodeLogTriggerType.LIBRARY_MANUAL]: "Промт из библиотеки",
  [NodeLogTriggerType.FREEFORM_MANUAL]: "Свободный промт",
  [NodeLogTriggerType.SUMMARY_FOR_CHILD]: "Пересказ для дочерней",
  [NodeLogTriggerType.PARENT_SUMMARY]: "Саммари родителя",
};

export const NODE_LOG_STATUS_LABEL: Record<NodeLogStatus, string> = {
  [NodeLogStatus.PENDING]: "ожидает",
  [NodeLogStatus.RUNNING]: "выполняется",
  [NodeLogStatus.AWAITING_DECISION]: "ждёт решения",
  [NodeLogStatus.SUCCESS]: "успешно",
  [NodeLogStatus.FAILED]: "ошибка",
  [NodeLogStatus.STOPPED]: "остановлено",
};

export const NODE_LOG_STATUS_TONE: Record<NodeLogStatus, BadgeTone> = {
  [NodeLogStatus.PENDING]: "neutral",
  [NodeLogStatus.RUNNING]: "info",
  [NodeLogStatus.AWAITING_DECISION]: "warning",
  [NodeLogStatus.SUCCESS]: "success",
  [NodeLogStatus.FAILED]: "danger",
  [NodeLogStatus.STOPPED]: "warning",
};

/** Раздел 19.7: общая шкала уровня рассуждений. */
export const REASONING_EFFORT_LABEL: Record<ReasoningEffort, string> = {
  [ReasoningEffort.LOW]: "низкий",
  [ReasoningEffort.MEDIUM]: "средний",
  [ReasoningEffort.HIGH]: "высокий",
  [ReasoningEffort.XHIGH]: "очень высокий",
  [ReasoningEffort.MAX]: "максимальный",
};

/** Раздел 15.2: причина строки «Переключено на аккаунт …» в «Диалоге». */
export const LLM_SWITCH_REASON_LABEL: Record<LlmSwitchReason, string> = {
  [LlmSwitchReason.START]: "стартовый аккаунт задачи",
  [LlmSwitchReason.KEPT]: "аккаунт не менялся",
  [LlmSwitchReason.WINDOW_PLANNED]: "новое окно лимита по плану",
  [LlmSwitchReason.WINDOW_BALANCE]: "более срочное окно лимита",
  [LlmSwitchReason.THRESHOLD_5H]: "порог 5-часового окна",
  [LlmSwitchReason.THRESHOLD_WEEK]: "порог недельного окна",
  [LlmSwitchReason.WEEK_EXHAUSTED]: "исчерпан недельный лимит",
  [LlmSwitchReason.RATE_LIMITED]: "исчерпан лимит",
  [LlmSwitchReason.LOGIN_REQUIRED]: "нужен повторный вход в прежний аккаунт",
  [LlmSwitchReason.DISABLED]: "прежний аккаунт выключен",
  [LlmSwitchReason.UNSUITABLE]: "прежний аккаунт не подходит для ноды",
  [LlmSwitchReason.ALL_ABOVE_THRESHOLD]: "все аккаунты выше порога — выбран наименее израсходованный",
};

/** Раздел 6.3, 15.1: статус моста `/remote-control`. */
export const REMOTE_CONTROL_STATUS_LABEL: Record<RemoteControlStatus, string> = {
  [RemoteControlStatus.CONNECTED]: "мост подключён",
  [RemoteControlStatus.RECONNECTING]: "мост переподключается",
  [RemoteControlStatus.DISCONNECTED]: "мост отключён",
  [RemoteControlStatus.UNAVAILABLE]: "Просмотр в claude.ai/code недоступен",
};

/** Раздел 15.5: блоки страницы «Мониторинг». */
export const SERVER_DEPENDENCY_LABEL: Record<ServerDependency, string> = {
  [ServerDependency.POSTGRES]: "PostgreSQL",
  [ServerDependency.REDIS]: "Redis",
  [ServerDependency.LLM_PROXY]: "LLM-прокси",
};

/** Очереди Celery (раздел 20.3): кто их обслуживает. */
export const CELERY_QUEUE_LABEL: Record<string, string> = {
  celery: "Периодические задачи (worker)",
  sessions: "Сессии задач (session-worker)",
  backups: "Бэкапы (backup-worker)",
};

export const STATS_PERIOD_LABEL: Record<StatsPeriod, string> = {
  [StatsPeriod.DAY]: "24 часа",
  [StatsPeriod.WEEK]: "7 дней",
};

export const VOLUME_LABEL: Record<VolumeName, string> = {
  [VolumeName.TASK_REPOS]: "Репозитории задач",
  [VolumeName.USER_FILES]: "Файлы задач",
  [VolumeName.CLAUDE_SESSIONS]: "Сессии агентов",
  [VolumeName.LOG_ARCHIVE]: "Архив логов",
};

export const CONTAINER_KIND_LABEL: Record<ContainerKind, string> = {
  [ContainerKind.SESSION]: "Сессия",
  [ContainerKind.NODE]: "Script-нода",
};

/** Раздел 18.4: категория события в ленте. */
export const EVENT_CATEGORY_LABEL: Record<EventCategory, string> = {
  [EventCategory.TASK]: "Задачи",
  [EventCategory.LLM_ACCOUNT]: "LLM-аккаунты",
  [EventCategory.PERIODIC]: "Периодические задачи",
  [EventCategory.BACKUP]: "Бэкапы",
  [EventCategory.PROFILE]: "Профиль",
};

/** Цвет события по его типу (раздел 18.2); остальные — информационные. */
const EVENT_TYPE_TONE: Record<string, BadgeTone> = {
  done: "success",
  backup_succeeded: "success",
  backup_verified: "success",
  periodic_task_recovered: "success",
  failed: "danger",
  autostart_failed: "danger",
  queue_launch_failed: "danger",
  library_prompt_failed: "danger",
  backup_failed: "danger",
  backup_verify_failed: "danger",
  periodic_task_failed: "danger",
  awaiting_decision: "warning",
  awaiting_decision_reminder: "warning",
  llm_login_required: "warning",
  llm_limit_wait: "warning",
  remote_control_disconnected: "warning",
  manual_queue_request_expired: "warning",
  gitlab_sync_failed: "warning",
  stale_ssh_key: "warning",
  calendar_login_required: "warning",
};

export function eventTone(eventType: string): BadgeTone {
  return EVENT_TYPE_TONE[eventType] ?? "info";
}

/** Разделы 6.4, 14.2, 14.3: что у завершённой задачи уже удалено — вручную или по сроку хранения. */
export const CLEANED_DATA_LABEL = {
  repo_cleaned_at: "Репозитории очищены",
  session_cleaned_at: "История сессии удалена",
  artifacts_cleaned_at: "Артефакты удалены",
} as const;

/** Раздел 15.8: что было по отмеченной задаче за день; день ещё не наступил — «запланирована». */
export const DAY_FACT_LABEL: Record<DayFact, string> = {
  done: "завершена",
  failed: "упала",
  worked: "была работа",
  no_work: "без работы",
};

export const DAY_FACT_TONE: Record<DayFact, BadgeTone> = {
  done: "success",
  failed: "danger",
  worked: "info",
  no_work: "neutral",
};

export const PLANNED_DAY_LABEL = "запланирована";

/** Раздел 19.8: состояние подключения Google Calendar. */
export const GOOGLE_CALENDAR_STATUS_LABEL: Record<GoogleCalendarStatus, string> = {
  connected: "подключён",
  needs_reauth: "нужен повторный вход",
};

export const GOOGLE_CALENDAR_STATUS_TONE: Record<GoogleCalendarStatus, BadgeTone> = {
  connected: "success",
  needs_reauth: "warning",
};

import {
  AppLogLevel,
  NodeLogStatus,
  NodeLogTriggerType,
  NodeType,
  EnvVariableScope,
  LlmAccountStatus,
  McpIsolationMode,
  PeriodicRunStatus,
  RepositoryRole,
  UserRole,
} from "@/lib/types";

/** Человекочитаемые подписи значений enum — в интерфейсе не показываем внутренние коды. */

/** Цвет бейджа статуса (варианты `Badge`). */
export type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral";

export const USER_ROLE_LABEL: Record<UserRole, string> = {
  [UserRole.ADMIN]: "Администратор",
  [UserRole.USER]: "Пользователь",
};

export const LLM_ACCOUNT_STATUS_LABEL: Record<LlmAccountStatus, string> = {
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

export const LLM_ACCOUNT_STATUS_TONE: Record<LlmAccountStatus, BadgeTone> = {
  [LlmAccountStatus.ACTIVE]: "success",
  [LlmAccountStatus.RATE_LIMITED]: "warning",
  [LlmAccountStatus.DISABLED]: "danger",
};

export const PERIODIC_RUN_STATUS_TONE: Record<PeriodicRunStatus, BadgeTone> = {
  [PeriodicRunStatus.SUCCESS]: "success",
  [PeriodicRunStatus.FAILED]: "danger",
  [PeriodicRunStatus.RUNNING]: "info",
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
